//
// INTEL CONFIDENTIAL
//
// Copyright 2013-2014 Intel Corporation All Rights Reserved.
//
// The source code contained or described herein and all documents related
// to the source code ("Material") are owned by Intel Corporation or its
// suppliers or licensors. Title to the Material remains with Intel Corporation
// or its suppliers and licensors. The Material contains trade secrets and
// proprietary and confidential information of Intel or its suppliers and
// licensors. The Material is protected by worldwide copyright and trade secret
// laws and treaty provisions. No part of the Material may be used, copied,
// reproduced, modified, published, uploaded, posted, transmitted, distributed,
// or disclosed in any way without Intel's prior express written permission.
//
// No license under any patent, copyright, trade secret or other intellectual
// property right is granted to or conferred upon you by disclosure or delivery
// of the Materials, either expressly, by implication, inducement, estoppel or
// otherwise. Any license under such intellectual property rights must be
// express and approved by Intel in writing.


angular.module('server').factory('createOrUpdateHostsThen', ['$q', 'requestSocket', 'throwIfError',
  function createOrUpdateHostsThenFactory ($q, requestSocket, throwIfError) {
    'use strict';

    /**
     * Creates or updates hosts as needed.
     * @param {Object} server
     * @param {Object} serverSpark
     * @returns {Object} A promise.
     */
    return function createOrUpdateHostsThen (server, serverSpark) {
      var deferred = $q.defer();

      var objects = server.address.reduce(function buildObjects (arr, address) {
        arr.push(_(server).omit(['address', 'pdsh']).extend({ address: address }).value());

        return arr;
      }, []);

      serverSpark.onceValue('data', throwIfError(function handleResponse (response) {
        var spark = requestSocket();

        var servers = response.body.objects;

        var toPost = objects.filter(function removeUsed (object) {
          return _.find(servers, { address: object.address }) === undefined;
        });
        var toPostPromise = hostWorkerThen(spark, 'sendPost', toPost);

        var toPut = _.difference(objects, toPost).filter(function removeDeployed (object) {
          return _.find(servers, { address: object.address }).state === 'undeployed';
        });
        var toPutPromise = hostWorkerThen(spark, 'sendPut', toPut);

        var leftovers = _.difference(objects, toPut, toPost);
        var unchangedServers = servers
          .filter(function mapToServers (server) {
            return _.find(leftovers, { address: server.address });
          })
          .reduce(function buildResponse (response, server) {
            response.body.objects.push({
              host: server
            });

            return response;
          }, {
            body: { objects: [] }
          });

        //@TODO: Switch to allSettled once
        //we are on 1.3.x and $q is prototype
        //based and can be extended.
        $q.all([toPostPromise, toPutPromise])
          .then(function combineResponses (responses) {
            responses = responses
              .concat(unchangedServers)
              .concat(function concatArrays (a, b) {
                return Array.isArray(a) ? a.concat(b) : undefined;
              });

            return _.merge.apply(_, responses);
          })
          .then(function resolveDeferred (response) {
            deferred.resolve(response);
          })
          .catch(function rejectDeferred (response) {
            deferred.reject(response);
          })
          .finally(function endSpark () {
            spark.end();
          });
      }));

      return deferred.promise;
    };

    /**
     * Creates or updates servers.
     * @param {Object} spark
     * @param {String} method
     * @param {Object} data
     * @returns {Object} A promise.
     */
    function hostWorkerThen (spark, method, data) {
      if (data.length === 0)
        return $q.when({});

      return spark[method]('/host', {
        json: { objects: data }
      }, true)
        .catch(function throwError (response) {
          throw response.error;
        });
    }
  }
]);