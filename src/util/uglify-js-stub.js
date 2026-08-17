/**
 * Minimal stub for uglify-js.
 *
 * uglify-js v2.8's main entry (tools/node.js) uses dynamic require.resolve() +
 * fs.readFileSync() + new Function() to load its lib files, which webpack cannot
 * bundle statically, causing "Cannot find module '../lib/utils.js'" at runtime.
 *
 * pug-filters only calls uglify.minify() when options.minify is true, which our
 * pug templates never set. This stub provides the minify function signature so
 * the module loads without error.
 */
exports.minify = function(code, options) {
  return { code: code, map: null };
};
