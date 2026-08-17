/**
 * Webpack 入口垫片（entry shim）
 *
 * 打包产物 dist/extension.js 以本文件为入口执行：
 *   1. 先抑制 Node 的各种 DeprecationWarning（punycode / util._extend /
 *      Buffer() / url.parse() 等）。这些警告来自捆绑的旧依赖
 *      （request、request-promise、urllib、tough-cookie 等），
 *      在不升级依赖的前提下无法消除，但会污染 Extension Host 日志。
 *      必须在任何 require 依赖之前设置，因此这里作为 webpack 入口，
 *      而非放在 extension.ts 内部（其 import 会被提升到模块体最前）。
 *   2. 再加载真正的扩展入口 src/extension.ts，并转发其
 *      activate / deactivate 导出（VS Code 通过 module.exports 读取）。
 */
process.noDeprecation = true;

module.exports = require('./extension.ts');