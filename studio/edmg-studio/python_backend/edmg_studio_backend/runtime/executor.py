"""Native TensorRT execution. Only import/use this module in an isolated child."""
from __future__ import annotations


class TensorExecutor:
    def __init__(self, serialized: bytes, device: int):
        import torch
        import tensorrt as trt
        self.torch, self.trt, self.device = torch, trt, device
        torch.cuda.set_device(device)
        self.logger = trt.Logger(trt.Logger.WARNING)
        trt.init_libnvinfer_plugins(self.logger, "")
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(serialized)
        if self.engine is None:
            raise RuntimeError("TensorRT rejected the serialized engine")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("TensorRT could not create an execution context")
        self.names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.inputs = [n for n in self.names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        self.outputs = [n for n in self.names if n not in self.inputs]
        if not self.inputs or not self.outputs:
            raise RuntimeError("TensorRT engine must declare at least one input and one output")

    def _torch_dtype(self, name: str):
        torch, trt = self.torch, self.trt
        types = {
            trt.float32: torch.float32,
            trt.float16: torch.float16,
            trt.int32: torch.int32,
            trt.int8: torch.int8,
            trt.bool: torch.bool,
        }
        if hasattr(trt, "bfloat16"):
            types[trt.bfloat16] = torch.bfloat16
        dtype = self.engine.get_tensor_dtype(name)
        if dtype not in types:
            raise RuntimeError(f"TensorRT binding {name!r} has unsupported dtype {dtype}")
        return types[dtype]

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        torch = self.torch
        supplied = set(inputs)
        expected = set(self.inputs)
        if supplied != expected:
            missing = sorted(expected - supplied)
            unexpected = sorted(supplied - expected)
            raise RuntimeError(
                f"TensorRT input bindings do not match the engine; missing={missing}, unexpected={unexpected}"
            )

        bound_inputs = {}
        for name in self.inputs:
            value = inputs[name]
            if not isinstance(value, torch.Tensor):
                raise TypeError(f"TensorRT input {name!r} must be a torch.Tensor")
            value = value.to(
                device=f"cuda:{self.device}",
                dtype=self._torch_dtype(name),
            ).contiguous()
            if not self.context.set_input_shape(name, tuple(value.shape)):
                raise RuntimeError(
                    f"TensorRT input {name!r} shape {tuple(value.shape)} is outside the compiled profile"
                )
            if not self.context.set_tensor_address(name, value.data_ptr()):
                raise RuntimeError(f"TensorRT input binding failed for {name!r}")
            bound_inputs[name] = value

        outputs = {}
        for name in self.outputs:
            shape = tuple(self.context.get_tensor_shape(name))
            if any(value <= 0 for value in shape):
                raise RuntimeError(f"TensorRT returned an unresolved output shape for {name!r}: {shape}")
            output = torch.empty(
                shape,
                device=f"cuda:{self.device}",
                dtype=self._torch_dtype(name),
            )
            if not self.context.set_tensor_address(name, output.data_ptr()):
                raise RuntimeError(f"TensorRT output binding failed for {name!r}")
            outputs[name] = output

        stream = torch.cuda.current_stream(self.device)
        if not self.context.execute_async_v3(stream.cuda_stream):
            raise RuntimeError("TensorRT execution failed")
        stream.synchronize()
        return outputs

    def __call__(self, value):
        if isinstance(value, dict):
            return self.execute(value)
        if len(self.inputs) != 1 or len(self.outputs) != 1:
            raise RuntimeError("Multi-binding TensorRT engines require named input tensors")
        return self.execute({self.inputs[0]: value})[self.outputs[0]]


def identity_engine():
    import tensorrt as trt
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    if builder is None:
        raise RuntimeError("TensorRT builder initialization failed")
    # TensorRT 11 is always strongly typed. No removed FP16 builder flags.
    flags = 0 if int(trt.__version__.split(".")[0]) >= 11 else 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
    network = builder.create_network(flags)
    value = network.add_input("input", trt.float32, (1, 4))
    layer = network.add_elementwise(value, value, trt.ElementWiseOperation.SUM)
    layer.get_output(0).name = "output"
    network.mark_output(layer.get_output(0))
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 64 * 1024 * 1024)
    engine = builder.build_serialized_network(network, config)
    if engine is None:
        raise RuntimeError("Synthetic TensorRT engine build failed")
    return bytes(engine)
