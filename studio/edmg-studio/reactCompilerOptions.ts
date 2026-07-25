const REACT_COMPILER_PLUGIN = [
  "babel-plugin-react-compiler",
  {
    compilationMode: "infer",
    panicThreshold: "none",
    target: "18",
  },
] as const;

function isProjectSource(id: string): boolean {
  if (!id) return false;
  if (id.includes("/node_modules/") || id.includes("\\node_modules\\")) return false;
  if (id.includes("/src/test/") || id.includes("\\src\\test\\")) return false;
  if (id.includes(".test.") || id.includes(".spec.")) return false;
  return id.endsWith(".ts") || id.endsWith(".tsx") || id.endsWith(".js") || id.endsWith(".jsx");
}

export function reactCompilerBabel(id: string) {
  if (!isProjectSource(id)) return undefined;
  return {
    babelrc: false,
    configFile: false,
    plugins: [REACT_COMPILER_PLUGIN],
  };
}
