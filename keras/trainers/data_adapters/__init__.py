import types

from keras.trainers.data_adapters import array_data_adapter
from keras.trainers.data_adapters import py_dataset_adapter
from keras.trainers.data_adapters.array_data_adapter import ArrayDataAdapter
from keras.trainers.data_adapters.generator_data_adapter import (
    GeneratorDataAdapter,
)
from keras.trainers.data_adapters.py_dataset_adapter import PyDatasetAdapter
from keras.trainers.data_adapters.tf_dataset_adapter import TFDatasetAdapter
from keras.trainers.data_adapters.torch_data_loader_adapter import (
    TorchDataLoaderAdapter,
)


def get_data_adapter(
    x,
    y=None,
    sample_weight=None,
    batch_size=None,
    steps_per_epoch=None,
    shuffle=False,
    class_weight=None,
):
    if array_data_adapter.can_convert_arrays((x, y, sample_weight)):
        return ArrayDataAdapter(
            x,
            y,
            sample_weight=sample_weight,
            class_weight=class_weight,
            shuffle=shuffle,
            batch_size=batch_size,
            steps=steps_per_epoch,
        )
    elif is_tf_dataset(x):
        # Unsupported args: y, sample_weight, shuffle
        if y is not None:
            raise_unsupported_arg("y", "the targets", "tf.data.Dataset")
        if sample_weight is not None:
            raise_unsupported_arg(
                "sample_weights", "the sample weights", "tf.data.Dataset"
            )
        return TFDatasetAdapter(x, class_weight=class_weight)
        # TODO: should we warn or not?
        # warnings.warn(
        #     "`shuffle=True` was passed, but will be ignored since the "
        #     "data `x` was provided as a tf.data.Dataset. The Dataset is "
        #     "expected to already be shuffled "
        #     "(via `.shuffle(tf.data.AUTOTUNE)`)"
        # )
    elif isinstance(x, py_dataset_adapter.PyDataset):
        if y is not None:
            raise_unsupported_arg("y", "the targets", "PyDataset")
        if sample_weight is not None:
            raise_unsupported_arg(
                "sample_weights", "the sample weights", "PyDataset"
            )
        return PyDatasetAdapter(x, class_weight=class_weight, shuffle=shuffle)
    elif is_torch_dataloader(x):
        if y is not None:
            raise_unsupported_arg("y", "the targets", "torch DataLoader")
        if sample_weight is not None:
            raise_unsupported_arg(
                "sample_weights", "the sample weights", "torch DataLoader"
            )
        if class_weight is not None:
            raise ValueError(
                "Argument `class_weight` is not supported for torch "
                f"DataLoader inputs. Received: class_weight={class_weight}"
            )
        return TorchDataLoaderAdapter(x)
        # TODO: should we warn or not?
        # warnings.warn(
        #     "`shuffle=True` was passed, but will be ignored since the "
        #     "data `x` was provided as a torch DataLoader. The DataLoader "
        #     "is expected to already be shuffled."
        # )
    elif isinstance(x, types.GeneratorType):
        if y is not None:
            raise_unsupported_arg("y", "the targets", "PyDataset")
        if sample_weight is not None:
            raise_unsupported_arg(
                "sample_weights", "the sample weights", "PyDataset"
            )
        if class_weight is not None:
            raise ValueError(
                "Argument `class_weight` is not supported for Python "
                f"generator inputs. Received: class_weight={class_weight}"
            )
        if shuffle:
            raise ValueError(
                "Argument `shuffle` is not supported for Python generator "
                f"inputs. Received: shuffle={shuffle}"
            )
        return GeneratorDataAdapter(x)
    else:
        raise ValueError(f"Unrecognized data type: x={x} (of type {type(x)})")


def raise_unsupported_arg(arg_name, arg_description, input_type):
    raise ValueError(
        f"When providing `x` as a {input_type}, `{arg_name}` "
        f"should not be passed. Instead, {arg_description} should "
        f"be included as part of the {input_type}."
    )


def is_tf_dataset(x):
    if hasattr(x, "__class__"):
        for parent in x.__class__.__mro__:
            if parent.__name__ == "DatasetV2" and str(
                parent.__module__
            ).startswith("tensorflow.python.types.data"):
                return True
    return False


def is_torch_dataloader(x):
    if hasattr(x, "__class__"):
        for parent in x.__class__.__mro__:
            if parent.__name__ == "DataLoader" and str(
                parent.__module__
            ).startswith("torch.utils.data"):
                return True
    return False
