//@ts-check

'use strict';

const path = require('path');

/**@type {import('webpack').Configuration}*/
const config = {
  target: 'node', // vscode extensions run in a Node.js-context 📖 -> https://webpack.js.org/configuration/node/

  entry: './src/extension.ts', // the entry point of this extension, 📖 -> https://webpack.js.org/configuration/entry-context/
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
  },
  {
    // uglify-js 使用动态 require，无法被 webpack 静态打包；
    // 且它是 pug 的可选依赖，运行时从 node_modules 加载即可。
    'uglify-js': 'commonjs uglify-js'
  }
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
  }
  
};
module.exports = config;