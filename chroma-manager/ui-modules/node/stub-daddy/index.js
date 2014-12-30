'use strict';

var Wiretree = require('wiretree');
var url = require('url');
var http = require('http');
var https = require('https');
var path = require('path');
var Validator = require('jsonschema').Validator;
var bunyan = require('bunyan');
var querystring = require('querystring');
var configulator = require('configulator');
var fs = require('fs');
var Promise = require('promise');

/**
 * Creates the wiretree
 * @param {String} [protocol]
 * @returns {Object}
 */
module.exports = function createWireTree (protocol) {
  var wireTree = new Wiretree(__dirname);

  wireTree.add(url, 'url');
  wireTree.add(path, 'path');
  wireTree.add(Validator, 'Validator');
  wireTree.add(bunyan, 'bunyan');
  wireTree.add(querystring, 'querystring');
  wireTree.add(configulator, 'configulator');
  wireTree.add(Promise, 'Promise');
  wireTree.add(fs, 'fs');
  wireTree.load('./webservice.js', 'webService');
  wireTree.load('./router.js', 'router');
  wireTree.load('./request-store.js', 'requestStore');
  wireTree.load('./matcher.js', 'requestMatcher');
  wireTree.load('./mock-state.js', 'mockState');
  wireTree.load('./dynamic-request.js', 'dynamicRequest');
  wireTree.load('./mock-status.js', 'mockStatus');
  wireTree.load('./register-api.js', 'registerApi');
  wireTree.load('./validators/register-api-validator.js', 'registerApiValidator');
  wireTree.load('./models.js', 'models');
  wireTree.load('./config.js', 'config');
  wireTree.load('./routes.js', 'routes');
  wireTree.load('./logger.js', 'logger');
  wireTree.load('./fsReadThen.js', 'fsReadThen');

  var config = wireTree.get('config');

  if (protocol)
    config.requestProtocol = protocol;

  var request = (config.requestProtocol === 'https') ? https : http;

  wireTree.add(request, 'request');

  return {
    config: wireTree.get('config'),
    webService: wireTree.get('webService'),
    validator: wireTree.get('registerApiValidator')
  };
};

