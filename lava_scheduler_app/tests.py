import cStringIO
import datetime
import json
import xmlrpclib

from django.contrib.auth.models import Permission, User
from django.test import TransactionTestCase
from django.test.client import Client

from django_testscenarios.ubertest import TestCase

from linaro_django_xmlrpc.models import AuthToken

from lava_scheduler_app.models import (
    Device,
    DeviceType,
    JSONDataError,
    Tag,
    TestJob)
from lava_scheduler_daemon.dbjobsource import DatabaseJobSource


# Based on http://www.technobabble.dk/2008/apr/02/xml-rpc-dispatching-through-django-test-client/
class TestTransport(xmlrpclib.Transport):
    """Handles connections to XML-RPC server through Django test client."""

    def __init__(self, user=None, password=None):
        self.client = Client()
        if user:
            success = self.client.login(username=user, password=password)
            if not success:
                raise AssertionError("Login attempt failed!")
        self._use_datetime = True

    def request(self, host, handler, request_body, verbose=0):
        self.verbose = verbose
        response = self.client.post(
            handler, request_body, content_type="text/xml")
        res = cStringIO.StringIO(response.content)
        res.seek(0)
        return self.parse_response(res)


class ModelFactory(object):

    def __init__(self):
        self._int = 0

    def getUniqueInteger(self):
        self._int += 1
        return self._int

    def getUniqueString(self, prefix='generic'):
        return '%s-%d' % (prefix, self.getUniqueInteger())

    def make_user(self):
        return User.objects.create_user(
            self.getUniqueString(),
            '%s@mail.invalid' % (self.getUniqueString(),),
            self.getUniqueString())

    def ensure_device_type(self, name=None):
        if name is None:
            name = self.getUniqueString('name')
        return DeviceType.objects.get_or_create(name=name)[0]

    def ensure_tag(self, name):
        return Tag.objects.get_or_create(name=name)[0]

    def make_device(self, device_type=None, hostname=None):
        if device_type is None:
            device_type = self.ensure_device_type()
        if hostname is None:
            hostname = self.getUniqueString()
        device = Device(device_type=device_type, hostname=hostname)
        device.save()
        return device

    def make_testjob(self, definition=None, submitter=None, **kwargs):
        if definition is None:
            definition = json.dumps({})
        if submitter is None:
            submitter = self.make_user()
        testjob = TestJob(
            definition=definition, submitter=submitter, **kwargs)
        testjob.save()
        return testjob


class TestCaseWithFactory(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        self.factory = ModelFactory()


class TestTestJob(TestCaseWithFactory):

    def test_from_json_and_user_sets_definition(self):
        self.factory.ensure_device_type(name='panda')
        definition = json.dumps({'device_type':'panda'})
        job = TestJob.from_json_and_user(definition, self.factory.make_user())
        self.assertEqual(definition, job.definition)

    def test_from_json_and_user_sets_submitter(self):
        self.factory.ensure_device_type(name='panda')
        user = self.factory.make_user()
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda'}), user)
        self.assertEqual(user, job.submitter)

    def test_from_json_and_user_sets_device_type(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda'}), self.factory.make_user())
        self.assertEqual(panda_type, job.requested_device_type)

    def test_from_json_and_user_sets_target(self):
        panda_board = self.factory.make_device(hostname='panda01')
        job = TestJob.from_json_and_user(
            json.dumps({'target':'panda01'}), self.factory.make_user())
        self.assertEqual(panda_board, job.requested_device)

    def test_from_json_and_user_does_not_set_device_type_from_target(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        self.factory.make_device(device_type=panda_type, hostname='panda01')
        job = TestJob.from_json_and_user(
            json.dumps({'target':'panda01'}), self.factory.make_user())
        self.assertEqual(None, job.requested_device_type)

    def test_from_json_and_user_sets_date_submitted(self):
        self.factory.ensure_device_type(name='panda')
        before = datetime.datetime.now()
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda'}), self.factory.make_user())
        after = datetime.datetime.now()
        self.assertTrue(before < job.submit_time < after)

    def test_from_json_and_user_sets_status_to_SUBMITTED(self):
        self.factory.ensure_device_type(name='panda')
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda'}), self.factory.make_user())
        self.assertEqual(job.status, TestJob.SUBMITTED)

    def test_from_json_and_user_sets_no_tags_if_no_tags(self):
        self.factory.ensure_device_type(name='panda')
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda', 'device_tags':[]}),
            self.factory.make_user())
        self.assertEqual(set(job.tags.all()), set([]))

    def test_from_json_and_user_errors_on_unknown_tags(self):
        self.factory.ensure_device_type(name='panda')
        self.assertRaises(
            JSONDataError, TestJob.from_json_and_user,
            json.dumps({'device_type':'panda', 'device_tags':['unknown']}),
            self.factory.make_user())

    def test_from_json_and_user_sets_tag_from_device_tags(self):
        self.factory.ensure_device_type(name='panda')
        self.factory.ensure_tag('tag')
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda', 'device_tags':['tag']}),
            self.factory.make_user())
        self.assertEqual(
            set(tag.name for tag in job.tags.all()), set(['tag']))

    def test_from_json_and_user_sets_multiple_tag_from_device_tags(self):
        self.factory.ensure_device_type(name='panda')
        self.factory.ensure_tag('tag1')
        self.factory.ensure_tag('tag2')
        job = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda', 'device_tags':['tag1', 'tag2']}),
            self.factory.make_user())
        self.assertEqual(
            set(tag.name for tag in job.tags.all()), set(['tag1', 'tag2']))

    def test_from_json_and_user_reuses_tag_objects(self):
        self.factory.ensure_device_type(name='panda')
        self.factory.ensure_tag('tag')
        job1 = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda', 'device_tags':['tag']}),
            self.factory.make_user())
        job2 = TestJob.from_json_and_user(
            json.dumps({'device_type':'panda', 'device_tags':['tag']}),
            self.factory.make_user())
        self.assertEqual(
            set(tag.pk for tag in job1.tags.all()),
            set(tag.pk for tag in job2.tags.all()))


class TestSchedulerAPI(TestCaseWithFactory):

    def server_proxy(self, user=None, password=None):
        return xmlrpclib.ServerProxy(
            'http://localhost/RPC2/',
            transport=TestTransport(user=user, password=password))

    def test_submit_job_rejects_anonymous(self):
        server = self.server_proxy()
        try:
            server.scheduler.submit_job("{}")
        except xmlrpclib.Fault as f:
            self.assertEqual(401, f.faultCode)
        else:
            self.fail("fault not raised")

    def test_submit_job_rejects_unpriv_user(self):
        User.objects.create_user('test', 'e@mail.invalid', 'test').save()
        server = self.server_proxy('test', 'test')
        try:
            server.scheduler.submit_job("{}")
        except xmlrpclib.Fault as f:
            self.assertEqual(403, f.faultCode)
        else:
            self.fail("fault not raised")

    def test_submit_job_sets_definition(self):
        user = User.objects.create_user('test', 'e@mail.invalid', 'test')
        user.user_permissions.add(
            Permission.objects.get(codename='add_testjob'))
        user.save()
        server = self.server_proxy('test', 'test')
        self.factory.ensure_device_type(name='panda')
        definition = json.dumps({'device_type':'panda'})
        job_id = server.scheduler.submit_job(definition)
        job = TestJob.objects.get(id=job_id)
        self.assertEqual(definition, job.definition)

    def test_cancel_job_rejects_anonymous(self):
        job = self.factory.make_testjob()
        server = self.server_proxy()
        try:
            server.scheduler.cancel_job(job.id)
        except xmlrpclib.Fault as f:
            self.assertEqual(401, f.faultCode)
        else:
            self.fail("fault not raised")

    def test_cancel_job_rejects_unpriv_user(self):
        job = self.factory.make_testjob()
        User.objects.create_user('test', 'e@mail.invalid', 'test').save()
        server = self.server_proxy('test', 'test')
        try:
            server.scheduler.cancel_job(job.id)
        except xmlrpclib.Fault as f:
            self.assertEqual(403, f.faultCode)
        else:
            self.fail("fault not raised")

    def test_cancel_job_cancels_job(self):
        user = User.objects.create_user('test', 'e@mail.invalid', 'test')
        user.save()
        job = self.factory.make_testjob(submitter=user)
        server = self.server_proxy('test', 'test')
        server.scheduler.cancel_job(job.id)
        job = TestJob.objects.get(pk=job.pk)
        self.assertEqual(TestJob.CANCELED, job.status)


class TransactionTestCaseWithFactory(TransactionTestCase):

    def setUp(self):
        TransactionTestCase.setUp(self)
        self.factory = ModelFactory()


class NonthreadedDatabaseJobSource(DatabaseJobSource):
    deferToThread = staticmethod(lambda f, *args, **kw: f(*args, **kw))


class TestDBJobSource(TransactionTestCaseWithFactory):

    def setUp(self):
        super(TestDBJobSource, self).setUp()
        self.source = NonthreadedDatabaseJobSource()
        # from the migration...
        now = datetime.datetime.now()
        new_user = User(
            username='lava-health', email='lava@lava.invalid', is_staff=False,
            is_active=True, is_superuser=False, last_login=now,
            date_joined=now)
        new_user.password = '!'
        new_user.save()


    def test_getBoardList(self):
        self.factory.make_device(hostname='panda01')
        self.assertEqual(['panda01'], self.source.getBoardList())

    def test_getJobForBoard_returns_json(self):
        device = self.factory.make_device(hostname='panda01')
        definition = {'foo': 'bar', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=device, definition=json.dumps(definition))
        self.assertEqual(
            definition, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_returns_health_check_if_health_unknown(self):
        device = self.factory.make_device(hostname='panda01')
        health_json = {'health_check': True, 'target': 'panda01'}
        device.health_status = Device.HEALTH_UNKNOWN
        device.device_type.health_check_job = json.dumps(health_json)
        device.save()
        device.device_type.save()
        definition = {'foo': 'bar', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=device, definition=json.dumps(definition))
        self.assertEqual(
            health_json, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_returns_health_check_if_no_last_health_job(self):
        device = self.factory.make_device(hostname='panda01')
        health_json = {'health_check': True, 'target': 'panda01'}
        device.health_status = Device.HEALTH_HEALTHY
        device.device_type.health_check_job = json.dumps(health_json)
        device.save()
        device.device_type.save()
        definition = {'foo': 'bar', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=device, definition=json.dumps(definition))
        self.assertEqual(
            health_json, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_returns_health_check_if_old_last_health_job(self):
        device = self.factory.make_device(hostname='panda01')
        health_json = {'health_check': True, 'target': 'panda01'}
        device.health_status = Device.HEALTH_HEALTHY
        device.device_type.health_check_job = json.dumps(health_json)
        device.last_health_report_job = self.factory.make_testjob(
            end_time=datetime.datetime.now() - datetime.timedelta(weeks=1))
        device.save()
        device.device_type.save()
        definition = {'foo': 'bar', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=device, definition=json.dumps(definition))
        self.assertEqual(
            health_json, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_returns_job_if_healthy_and_last_health_job_recent(self):
        device = self.factory.make_device(hostname='panda01')
        health_json = {'health_check': True, 'target': 'panda01'}
        device.health_status = Device.HEALTH_HEALTHY
        device.device_type.health_check_job = json.dumps(health_json)
        device.last_health_report_job = self.factory.make_testjob(
            end_time=datetime.datetime.now() - datetime.timedelta(hours=1))
        device.save()
        device.device_type.save()
        definition = {'foo': 'bar', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=device, definition=json.dumps(definition))
        self.assertEqual(
            definition, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_returns_None_if_no_job(self):
        self.factory.make_device(hostname='panda01')
        self.assertEqual(
            None, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_considers_device_type(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        self.factory.make_device(hostname='panda01', device_type=panda_type)
        definition = {'foo': 'bar'}
        self.factory.make_testjob(
            requested_device_type=panda_type,
            definition=json.dumps(definition))
        definition['target'] = 'panda01'
        self.assertEqual(
            definition, self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_prefers_older(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        panda01 = self.factory.make_device(
            hostname='panda01', device_type=panda_type)
        first_definition = {'foo': 'bar', 'target': 'panda01'}
        second_definition = {'foo': 'baz', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=panda01, definition=json.dumps(first_definition),
            submit_time=datetime.datetime.now() - datetime.timedelta(days=1))
        self.factory.make_testjob(
            requested_device=panda01, definition=json.dumps(second_definition),
            submit_time=datetime.datetime.now())
        self.assertEqual(
            first_definition,
            self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_prefers_directly_targeted(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        panda01 = self.factory.make_device(
            hostname='panda01', device_type=panda_type)
        type_definition = {'foo': 'bar'}
        self.factory.make_testjob(
            requested_device_type=panda_type,
            definition=json.dumps(type_definition),
            submit_time=datetime.datetime.now() - datetime.timedelta(days=1))
        device_definition = {'foo': 'baz', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=panda01,
            definition=json.dumps(device_definition))
        self.assertEqual(
            device_definition,
            self.source.getJobForBoard('panda01'))

    def test_getJobForBoard_avoids_targeted_to_other_board_of_same_type(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        panda01 = self.factory.make_device(
            hostname='panda01', device_type=panda_type)
        self.factory.make_device(hostname='panda02', device_type=panda_type)
        definition = {'foo': 'bar', 'target': 'panda01'}
        self.factory.make_testjob(
            requested_device=panda01,
            definition=json.dumps(definition))
        self.assertEqual(
            None,
            self.source.getJobForBoard('panda02'))

    def _makeBoardWithTags(self, tags):
        board = self.factory.make_device()
        for tag_name in tags:
            board.tags.add(Tag.objects.get_or_create(name=tag_name)[0])
        return board

    def _makeJobWithTagsForBoard(self, tags, board):
        job = self.factory.make_testjob(requested_device=board)
        for tag_name in tags:
            job.tags.add(Tag.objects.get_or_create(name=tag_name)[0])
        return job

    def assertBoardWithTagsGetsJobWithTags(self, board_tags, job_tags):
        board = self._makeBoardWithTags(board_tags)
        self._makeJobWithTagsForBoard(job_tags, board)
        self.assertEqual(
            board.hostname,
            self.source.getJobForBoard(board.hostname)['target'])

    def assertBoardWithTagsDoesNotGetJobWithTags(self, board_tags, job_tags):
        board = self._makeBoardWithTags(board_tags)
        self._makeJobWithTagsForBoard(job_tags, board)
        self.assertEqual(
            None,
            self.source.getJobForBoard(board.hostname))

    def test_getJobForBoard_does_not_return_job_if_board_lacks_tag(self):
        self.assertBoardWithTagsDoesNotGetJobWithTags([], ['tag'])

    def test_getJobForBoard_returns_job_if_board_has_tag(self):
        self.assertBoardWithTagsGetsJobWithTags(['tag'], ['tag'])

    def test_getJobForBoard_returns_job_if_board_has_both_tags(self):
        self.assertBoardWithTagsGetsJobWithTags(['tag1', 'tag2'], ['tag1', 'tag2'])

    def test_getJobForBoard_returns_job_if_board_has_extra_tags(self):
        self.assertBoardWithTagsGetsJobWithTags(['tag1', 'tag2'], ['tag1'])

    def test_getJobForBoard_does_not_return_job_if_board_has_only_one_tag(self):
        self.assertBoardWithTagsDoesNotGetJobWithTags(['tag1'], ['tag1', 'tag2'])

    def test_getJobForBoard_does_not_return_job_if_board_has_unrelated_tag(self):
        self.assertBoardWithTagsDoesNotGetJobWithTags(['tag1'], ['tag2'])

    def test_getJobForBoard_does_not_return_job_if_only_one_tag_matches(self):
        self.assertBoardWithTagsDoesNotGetJobWithTags(['tag1', 'tag2'], ['tag1', 'tag3'])

    def test_getJobForBoard_sets_start_time(self):
        device = self.factory.make_device(hostname='panda01')
        job = self.factory.make_testjob(requested_device=device)
        before = datetime.datetime.now()
        self.source.getJobForBoard('panda01')
        after = datetime.datetime.now()
        # reload from the database
        job = TestJob.objects.get(pk=job.pk)
        self.assertTrue(before < job.start_time < after)

    def test_getJobForBoard_set_statuses(self):
        device = self.factory.make_device(hostname='panda01')
        job = self.factory.make_testjob(requested_device=device)
        self.source.getJobForBoard('panda01')
        # reload from the database
        job = TestJob.objects.get(pk=job.pk)
        device = Device.objects.get(pk=device.pk)
        self.assertEqual(
            (Device.RUNNING, TestJob.RUNNING),
            (device.status, job.status))

    def test_getJobForBoard_sets_running_job(self):
        device = self.factory.make_device(hostname='panda01')
        job = self.factory.make_testjob(requested_device=device)
        self.source.getJobForBoard('panda01')
        # reload from the database
        job = TestJob.objects.get(pk=job.pk)
        device = Device.objects.get(pk=device.pk)
        self.assertEqual(job, device.current_job)

    def test_getJobForBoard_creates_token(self):
        device = self.factory.make_device(hostname='panda01')
        job = self.factory.make_testjob(requested_device=device)
        self.source.getJobForBoard('panda01')
        # reload from the database
        job = TestJob.objects.get(pk=job.pk)
        device = Device.objects.get(pk=device.pk)
        self.assertIsNotNone(job.submit_token)
        self.assertEqual(job.submitter, job.submit_token.user)

    def test_getJobForBoard_inserts_target_into_json(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        self.factory.make_device(hostname='panda01', device_type=panda_type)
        definition = {'foo': 'bar'}
        self.factory.make_testjob(
            requested_device_type=panda_type,
            definition=json.dumps(definition))
        json_data = self.source.getJobForBoard('panda01')
        self.assertIn('target', json_data)
        self.assertEqual('panda01', json_data['target'])

    def test_getJobForBoard_inserts_submit_token_into_json(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        self.factory.make_device(hostname='panda01', device_type=panda_type)
        definition = {
            'actions': [
                {
                    "command": "submit_results",
                    "parameters":
                    {
                        "server": "http://test-server/RPC2/",
                        "stream": "/private/personal/test/test/",
                    }
                }
            ]
        }
        job = self.factory.make_testjob(
            requested_device_type=panda_type,
            definition=json.dumps(definition))
        json_data = self.source.getJobForBoard('panda01')
        job = TestJob.objects.get(pk=job.pk)
        submit_job_params = json_data['actions'][0]['parameters']
        self.assertIn('token', submit_job_params)
        self.assertEqual(job.submit_token.secret, submit_job_params['token'])

    def test_getJobForBoard_adds_user_to_url(self):
        panda_type = self.factory.ensure_device_type(name='panda')
        self.factory.make_device(hostname='panda01', device_type=panda_type)
        user = User.objects.create_user('test', 'e@mail.invalid', 'test')
        user.save()
        definition = {
            'actions': [
                {
                    "command": "submit_results",
                    "parameters":
                    {
                        "server": "http://test-server/RPC2/",
                        "stream": "/private/personal/test/test/",
                    }
                }
            ]
        }
        job = self.factory.make_testjob(
            requested_device_type=panda_type, submitter=user,
            definition=json.dumps(definition))
        json_data = self.source.getJobForBoard('panda01')
        job = TestJob.objects.get(pk=job.pk)
        submit_job_params = json_data['actions'][0]['parameters']
        self.assertEqual("http://test@test-server/RPC2/", submit_job_params['server'])

    def get_device_and_running_job(self):
        device = self.factory.make_device(hostname='panda01')
        job = self.factory.make_testjob(requested_device=device)
        self.source.getJobForBoard('panda01')
        return device, TestJob.objects.get(pk=job.pk)

    def test_jobCompleted_set_statuses_success(self):
        device, job = self.get_device_and_running_job()
        self.source.jobCompleted('panda01', 0)
        job = TestJob.objects.get(pk=job.pk)
        device = Device.objects.get(pk=device.pk)
        self.assertEqual(
            (Device.IDLE, TestJob.COMPLETE),
            (device.status, job.status))

    def test_jobCompleted_set_statuses_failure(self):
        device, job = self.get_device_and_running_job()
        self.source.jobCompleted('panda01', 1)
        job = TestJob.objects.get(pk=job.pk)
        device = Device.objects.get(pk=device.pk)
        self.assertEqual(
            (Device.IDLE, TestJob.INCOMPLETE),
            (device.status, job.status))

    def test_jobCompleted_works_on_device_type_targeted(self):
        device = self.factory.make_device(hostname='panda01')
        job = self.factory.make_testjob(
            requested_device_type=device.device_type)
        self.source.getJobForBoard('panda01')
        self.source.jobCompleted('panda01', 0)
        job = TestJob.objects.get(pk=job.pk)
        device = Device.objects.get(pk=device.pk)
        self.assertEqual(
            (Device.IDLE, TestJob.COMPLETE),
            (device.status, job.status))

    def test_jobCompleted_sets_end_time(self):
        device, job = self.get_device_and_running_job()
        before = datetime.datetime.now()
        self.source.jobCompleted('panda01', 0)
        after = datetime.datetime.now()
        job = TestJob.objects.get(pk=job.pk)
        self.assertTrue(before < job.end_time < after)

    def test_jobCompleted_clears_current_job(self):
        device, job = self.get_device_and_running_job()
        self.source.jobCompleted('panda01', 0)
        device = Device.objects.get(pk=device.pk)
        self.assertEquals(None, device.current_job)

    def test_jobCompleted_deletes_token(self):
        device, job = self.get_device_and_running_job()
        token = job.submit_token
        self.source.jobCompleted('panda01', 0)
        self.assertRaises(
            AuthToken.DoesNotExist,
            AuthToken.objects.get, pk=token.pk)

    def test_getLogFileForJobOnBoard_returns_writable_file(self):
        device, job = self.get_device_and_running_job()
        definition = {'foo': 'bar'}
        self.factory.make_testjob(
            requested_device=device, definition=json.dumps(definition))
        log_file = self.source.getLogFileForJobOnBoard('panda01')
        log_file.write('a')
        log_file.close()
