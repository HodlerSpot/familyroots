// Metro config for the FutureRoots Expo app inside the npm workspace monorepo.
//
// The shared packages (@futureroots/{types,api-client,tokens}) live at the repo
// root under packages/*, and npm hoists most dependencies to the root
// node_modules. Metro must therefore (1) watch the whole workspace so edits to
// the shared packages hot-reload, and (2) resolve modules from both this app's
// node_modules and the hoisted root node_modules. The shared packages are
// React-free/DOM-free plain TS, so there is no duplicate-React hazard here;
// disabling hierarchical lookup keeps resolution deterministic to exactly these
// two folders.
const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, "..", "..");

const config = getDefaultConfig(projectRoot);

// 1. Watch the whole monorepo (so packages/* changes are picked up).
config.watchFolders = [workspaceRoot];

// 2. Resolve from this app first, then the hoisted root node_modules.
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];

// 3. Only walk the two folders above (no parent-dir crawling), so a dependency
//    resolves to a single, predictable copy.
config.resolver.disableHierarchicalLookup = true;

module.exports = config;
