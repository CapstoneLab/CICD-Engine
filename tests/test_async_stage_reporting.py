from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from app import orchestrator as module
from app.orchestrator import LocalOrchestrator
from app.models import PipelineRun, PipelineStep


def test_reports_do_not_block_execution_but_deploy_waits_for_server(tmp_path, monkeypatch):
    obj=LocalOrchestrator(tmp_path, callback_url='http://backend')
    started=Event(); release=Event(); deployed=Event(); calls=[]
    def post(**kwargs):
        step=kwargs['payload']['step'];calls.append((step['step_name'],step['status']))
        if len(calls)==1:
            started.set()
            assert release.wait(5)
        return True, 'ok'
    monkeypatch.setattr(module,'post_step_callback',post)
    run=PipelineRun(run_id='test',repo_url='https://github.com/a/b',branch='main',runtime_type='node',steps=[])
    def execute(*args):
        step=PipelineStep(step_name='clone',status='running')
        obj._send_step_callback(run,tmp_path,step,run.repo_url,'main')
        assert started.wait(5)
        # The network request is still blocked; execution can finish and enqueue
        # its result and the next stage without waiting for HTTP.
        step.status='success'
        obj._send_step_callback(run,tmp_path,step,run.repo_url,'main')
        obj._send_step_callback(run,tmp_path,PipelineStep(step_name='install',status='running'),run.repo_url,'main')
        obj._send_step_callback(run,tmp_path,PipelineStep(step_name='deploy',status='running'),run.repo_url,'main')
        deployed.set()
        return run,tmp_path
    monkeypatch.setattr(obj,'_run',execute)
    with ThreadPoolExecutor() as executor:
        future=executor.submit(obj.run,run.repo_url,'main')
        assert started.wait(5)
        assert not deployed.is_set()
        release.set()
        future.result(timeout=5)
    assert calls==[('clone','running'),('clone','success'),('install','running'),('deploy','running')]
    assert deployed.is_set()


def test_failed_report_prevents_deployment(tmp_path,monkeypatch):
    obj=LocalOrchestrator(tmp_path,callback_url='http://backend')
    monkeypatch.setattr(module,'post_step_callback',lambda **kwargs:(False,'unavailable'))
    run=PipelineRun(run_id='test',repo_url='https://github.com/a/b',branch='main',runtime_type='node',steps=[])
    def execute(*args):
        obj._send_step_callback(run,tmp_path,PipelineStep(step_name='security_gate',status='success'),run.repo_url,'main')
        obj._send_step_callback(run,tmp_path,PipelineStep(step_name='deploy',status='running'),run.repo_url,'main')
        pytest.fail('must not deploy without persisted gate')
    monkeypatch.setattr(obj,'_run',execute)
    with pytest.raises(RuntimeError):obj.run(run.repo_url,'main')
