describe('Eula', function () {
  'use strict';

  var $scope;

  beforeEach(module('controllers', 'models', 'ngResource', 'services'));

  beforeEach(module(function ($provide) {
    // Mock out deps.
    $provide.value('dialog', {
      close: jasmine.createSpy('dialogClose')
    });

    $provide.value('HELP_TEXT', {
      eula: 'foo'
    });

    $provide.value('credentials', {
      username: 'foo',
      password: 'bar'
    });

    $provide.value('doneCallback', jasmine.createSpy('doneCallback'));
  }));

  beforeEach(inject(function ($controller, $rootScope) {
    $scope = $rootScope.$new();

    $controller('EulaCtrl', {$scope: $scope});
  }));

  it('should have actions accept and reject the eula', function () {
    expect($scope.eulaCtrl.accept).toEqual(jasmine.any(Function));
    expect($scope.eulaCtrl.reject).toEqual(jasmine.any(Function));
  });

  it('should perform the appropriate actions on accept', inject(function (doneCallback, dialog, $httpBackend) {
    $httpBackend.expectPOST('/api/session/').respond(201);
    $httpBackend.expectGET('/api/session/').respond({
      user: {
        accepted_eula: false
      }
    });
    $httpBackend.expectPUT('/api/user/', {accepted_eula: true}).respond(202);

    $scope.eulaCtrl.accept();

    // Flush the POST and GET
    $httpBackend.flush(2);

    expect(dialog.close).not.toHaveBeenCalled();

    expect(doneCallback).not.toHaveBeenCalled();

    // Flush the PUT
    $httpBackend.flush(1);

    expect(dialog.close).toHaveBeenCalled();

    expect(doneCallback).toHaveBeenCalled();
  }));

  it('should perform the appropriate actions on reject', inject(function (doneCallback, dialog, $httpBackend) {
    $httpBackend.expectPOST('/api/session/').respond(201);
    $httpBackend.expectGET('/api/session/').respond({
      user: {
        accepted_eula: true
      }
    });
    $httpBackend.expectPUT('/api/user/', {accepted_eula: false}).respond(202);
    $httpBackend.expectDELETE('/api/session/').respond(204);

    $scope.eulaCtrl.reject();

    // Flush the POST, GET, and PUT
    $httpBackend.flush(3);

    expect(dialog.close).toHaveBeenCalled();

    expect(doneCallback).not.toHaveBeenCalled();

    // Flush the DELETE
    $httpBackend.flush(1);

    expect(doneCallback).toHaveBeenCalled();
  }));
});