"""Test for Jax backend distribution_lib.py."""

import os

import jax
import numpy as np
import pytest

from keras import backend
from keras import layers
from keras import models
from keras import testing
from keras.backend import distribution_lib as backend_dlib
from keras.distribution import distribution_lib

if backend.backend() == "jax":
    # Due to https://github.com/google/jax/issues/17188, we can't
    # override the XLA flag after the JAX back init. We have to
    # run this at top level to let JAX pick the flag value.
    xla_flags = os.getenv("XLA_FLAGS") or ""
    # Don't override user-specified device count, or other XLA flags.
    if "xla_force_host_platform_device_count" not in xla_flags:
        os.environ["XLA_FLAGS"] = (
            xla_flags + " --xla_force_host_platform_device_count=8"
        )


@pytest.mark.skipif(
    backend.backend() != "jax",
    reason="Backend specific test",
)
class JaxDistributionLibTest(testing.TestCase):
    def test_list_devices(self):
        self.assertEqual(len(distribution_lib.list_devices()), 8)
        self.assertEqual(len(distribution_lib.list_devices("cpu")), 8)
        self.assertEqual(len(distribution_lib.list_devices("cpu")), 8)

    def test_to_jax_mesh(self):
        devices = [f"cpu:{i}" for i in range(8)]
        shape = (4, 2)
        axis_names = ["batch", "model"]

        mesh = distribution_lib.DeviceMesh(shape, axis_names, devices)
        jax_mesh = backend_dlib._to_jax_mesh(mesh)

        self.assertIsInstance(jax_mesh, jax.sharding.Mesh)
        self.assertEqual(jax_mesh.devices.shape, shape)
        self.assertEqual(jax_mesh.axis_names, ("batch", "model"))

    def test_to_jax_layout(self):
        axes = ["data", None]
        mesh = distribution_lib.DeviceMesh(
            (4, 2), ["data", "model"], [f"cpu:{i}" for i in range(8)]
        )
        layout = distribution_lib.TensorLayout(axes, mesh)
        jax_sharding = backend_dlib._to_jax_layout(layout)
        jax_mesh = backend_dlib._to_jax_mesh(mesh)
        self.assertEqual(
            jax_sharding,
            jax.sharding.NamedSharding(
                jax_mesh, jax.sharding.PartitionSpec("data", None)
            ),
        )

    def test_validation_for_device_mesh(self):
        axes = ["data", None]
        layout = distribution_lib.TensorLayout(axes, device_mesh=None)

        with self.assertRaisesRegex(
            ValueError, "Cannot create sharding when device mesh is not set"
        ):
            backend_dlib._to_jax_layout(layout)

    def test_variable_assignment_reuse_layout(self):
        shape = (4, 2)
        axis_names = ["batch", "model"]
        device_mesh = distribution_lib.DeviceMesh(
            shape, axis_names, backend_dlib.list_devices()
        )
        layout_map = distribution_lib.LayoutMap(device_mesh)
        layout_map[".*dense.*kernel"] = distribution_lib.TensorLayout(
            [None, "model"]
        )
        layout_map[".*dense.*bias"] = distribution_lib.TensorLayout(["model"])

        distribution = distribution_lib.ModelParallel(
            device_mesh, layout_map, batch_dim_name="batch"
        )

        with distribution.scope():
            dense_layer = layers.Dense(8)
            dense_layer.build((16, 16))

        self.assertEqual(
            dense_layer.kernel._value.sharding.spec, (None, "model")
        )
        self.assertEqual(dense_layer.bias._value.sharding.spec, ("model",))

        # Assign a numpy value to dense layer to mimic the model weight loading
        new_kernel = np.random.normal(size=(16, 8))
        new_bias = np.random.normal(size=(8))
        dense_layer.kernel.assign(new_kernel)
        dense_layer.bias.assign(new_bias)

        # Make sure the loaded value still use the layout when it is
        # initialized, even outside of the distribution scope.
        self.assertEqual(
            dense_layer.kernel._value.sharding.spec, (None, "model")
        )
        self.assertEqual(dense_layer.bias._value.sharding.spec, ("model",))

    def test_e2e_data_parallel_model(self):
        distribution = distribution_lib.DataParallel(
            devices=backend_dlib.list_devices()
        )

        with distribution.scope():
            inputs = layers.Input(shape=[28, 28, 1])
            y = layers.Flatten()(inputs)
            y = layers.Dense(units=200, use_bias=False, activation="relu")(y)
            y = layers.Dropout(0.4)(y)
            y = layers.Dense(units=10, activation="softmax")(y)
            model = models.Model(inputs=inputs, outputs=y)

        # Make sure all the weights are properly sharded.
        for weight in model.weights:
            self.assertTrue(weight._value.sharding.is_fully_replicated)

        inputs = np.random.normal(size=(32, 28, 28, 1))
        labels = np.random.normal(size=(32, 10))

        validation_inputs = np.random.normal(size=(32, 28, 28, 1))
        validation_labels = np.random.normal(size=(32, 10))

        with distribution.scope():
            # Training
            model.compile(loss="mse", optimizer="SGD")
            model.fit(inputs, labels)

            # Validation
            model.evaluate(validation_inputs, validation_labels)

            # Prediction
            predictions = model.predict(inputs)
            self.assertEqual(predictions.shape, (32, 10))

    def test_e2e_model_parallel_model(self):
        shape = (4, 2)
        axis_names = ["batch", "model"]
        device_mesh = distribution_lib.DeviceMesh(
            shape, axis_names, backend_dlib.list_devices()
        )

        layout_map = distribution_lib.LayoutMap(device_mesh)
        layout_map[".*dense.*kernel"] = distribution_lib.TensorLayout(
            [None, "model"]
        )
        layout_map[".*dense.*bias"] = distribution_lib.TensorLayout(["model"])

        distribution = distribution_lib.ModelParallel(
            device_mesh, layout_map, batch_dim_name="batch"
        )
        with distribution.scope():
            inputs = layers.Input(shape=[28, 28, 1])
            y = layers.Flatten()(inputs)
            y = layers.Dense(units=200, use_bias=False, activation="relu")(y)
            y = layers.Dropout(0.4)(y)
            y = layers.Dense(units=10, activation="softmax")(y)
            model = models.Model(inputs=inputs, outputs=y)

        for weight in model.weights:
            if "kernel" in weight.name:
                self.assertEqual(weight._value.sharding.spec, (None, "model"))
            elif "bias" in weight.name:
                self.assertEqual(weight._value.sharding.spec, ("model",))
            else:
                self.assertTrue(weight._value.sharding.is_fully_replicated)

        inputs = np.random.normal(size=(32, 28, 28, 1))
        labels = np.random.normal(size=(32, 10))

        validation_inputs = np.random.normal(size=(32, 28, 28, 1))
        validation_labels = np.random.normal(size=(32, 10))

        with distribution.scope():
            # Training
            model.compile(loss="mse", optimizer="SGD")
            model.fit(inputs, labels)

            # Validation
            model.evaluate(validation_inputs, validation_labels)

            # Prediction
            predictions = model.predict(inputs)
            self.assertEqual(predictions.shape, (32, 10))