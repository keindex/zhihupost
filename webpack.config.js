//@ts-check

'use strict';

const path = require('path');
const webpack = require('webpack');

/**@type {import('webpack').Configuration}*/
const config = {
  target: 'node', // vscode extensions run in a Node.js-context 📖 -> https://webpack.js.org/configuration/node/

  entry: './src/entry.js', // 先执行 entry.js（抑制弃用警告），再加载 extension.ts
  output:  { 


    // the bundle is stored in the 'dist' folder (check package.json), 📖 -> https://webpack.js.org/configuration/output/
    path: path.resolve(__dirname, 'dist'),
    filename: 'extension.js',
    libraryTarget: 'commonjs2',
    devtoolModuleFilenameTemplate: '../[resource-path]'
  },
  devtool: 'source-map',
  externals: [{
    vscode: 'commonjs vscode', // the vscode-module is created on-the-fly and must be excluded. Add other modules that cannot be webpack'ed, 📖 -> https://webpack.js.org/configuration/externals/
  }
  // 注意：不要把 uglify-js 列为 external！
  // uglify-js 是 pug-filters 的依赖，会在模块加载时被急切 require；
  // 若列为 external 则打包产物保留运行时 require("uglify-js")，
  // 而 .vscodeignore 排除了 node_modules/，VSIX 中无此模块 -> 激活报
  // "Cannot find module 'uglify-js'"。让 webpack 静态打包它即可。
  ],
  resolve: {
    // support reading TypeScript and JavaScript files, 📖 -> https://github.com/TypeStrong/ts-loader
    extensions: ['.ts', '.js'],
  },
  module: {
    rules: [
      {
        test: /\.test\.ts$/,
          exclude: /node_modules/,
            use: [
              { loader: 'ignore-loader'}
            ]
      },
      {
        test: /\.ts$/,
          exclude: /node_modules/,
            use: [
              {
                loader: 'ts-loader'
              }
            ]
      }
    ]
  },
  plugins: [
    // uglify-js v2.8 main = tools/node.js, which uses dynamic require.resolve()
    // + fs.readFileSync() + new Function() — webpack cannot bundle this.
    // pug-filters only uses uglify.minify() when options.minify is true (never in our templates).
    // Replace with a minimal stub that exports the minify function.
    new webpack.NormalModuleReplacementPlugin(
      /uglify-js$/,
      path.resolve(__dirname, 'src/util/uglify-js-stub.js')
    )
  ]
  
};
module.exports = config;