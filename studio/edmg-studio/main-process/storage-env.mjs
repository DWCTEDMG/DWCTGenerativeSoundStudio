import path from "node:path";

export function buildCacheEnvPaths(cacheRoot) {
  const root = path.resolve(cacheRoot);
  const huggingFaceRoot = path.join(root, "huggingface");
  const huggingFaceHubCache = path.join(huggingFaceRoot, "hub");
  const huggingFaceAssetsCache = path.join(huggingFaceRoot, "assets");

  return {
    EDMG_STUDIO_CACHE_DIR: root,
    PIP_CACHE_DIR: path.join(root, "pip"),
    XDG_CACHE_HOME: path.join(root, "xdg"),
    HF_HOME: huggingFaceRoot,
    HF_HUB_CACHE: huggingFaceHubCache,
    HF_XET_CACHE: path.join(huggingFaceRoot, "xet"),
    HF_ASSETS_CACHE: huggingFaceAssetsCache,
    HUGGINGFACE_HUB_CACHE: huggingFaceHubCache,
    HUGGINGFACE_ASSETS_CACHE: huggingFaceAssetsCache,
    TRANSFORMERS_CACHE: path.join(root, "transformers"),
    TORCH_HOME: path.join(root, "torch"),
    NLTK_DATA: path.join(root, "nltk_data"),
    WHISPER_CACHE_DIR: path.join(root, "whisper"),
    MPLCONFIGDIR: path.join(root, "matplotlib"),
    TMP: path.join(root, "tmp"),
    TEMP: path.join(root, "tmp"),
  };
}
