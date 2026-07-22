// babel-preset-expo already wires expo-router and React Native transforms for
// SDK 50+ (the standalone expo-router/babel plugin was removed).
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
  };
};
