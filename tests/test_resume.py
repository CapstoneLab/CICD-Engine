import json
import subprocess
from pathlib import Path
import pytest
from app.orchestrator import LocalOrchestrator
from app.models import PipelineRun, PipelineStep, StepRunResult
from app.resume import workspace_digest
from app.utils.filesystem import save_json


def retained(tmp_path):
    run_id='run-20261116-001';run=tmp_path/'runs'/run_id;repo=tmp_path/'workspace'/run_id/'repo'
    repo.mkdir(parents=True);run.mkdir(parents=True);(run/'logs').mkdir()
    subprocess.run(['git','init','-q',str(repo)],check=True)
    (repo/'source.txt').write_text('original source')
    subprocess.run(['git','add','.'],cwd=repo,check=True)
    subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','fixture'],cwd=repo,check=True)
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    names=['clone','install','lightweight-security','test','deep-security','security_gate','build','deploy']
    steps=[PipelineStep(step_name=n,status='success' if i<5 else 'failed' if i==5 else 'skipped',
        started_at='2026-11-16T00:00:00+09:00',finished_at='2026-11-16T00:00:01+09:00') for i,n in enumerate(names)]
    pipeline=PipelineRun(run_id=run_id,repo_url='https://github.com/test/repo',branch='main',status='failed',
        started_at='2026-11-16T00:00:00+09:00',finished_at='2026-11-16T00:00:01+09:00',steps=steps)
    save_json(run/'pipeline_result.json',pipeline.to_dict());save_json(run/'callback_result.json',{'job_id':'job'})
    save_json(run/'security_verdict.json',{'verdict':'block_pending_approval','scanned_commit_sha':sha})
    findings=[dict(scanner_name='semgrep',rule_id='test',severity='high',title='test',file_path='source.txt',line_number=1,message='test',cwe='CWE-502')]
    save_json(run/'security_findings.json',findings);save_json(run/'security_summary.json',[{'scan':'unchanged'}])
    save_json(run/'resume_checkpoint.json',dict(job_id='job',commit_sha=sha,workspace_digest=workspace_digest(repo),
        selected_items=['CWE-502'],steps=[dict(name=n,kind='builtin',uses=n) for n in ['build','deploy']]))
    (repo/'installed-dependency').write_text('reuse me') # ignored by checkpoint only if ignored; remove from digest fixture
    (repo/'installed-dependency').unlink()
    return run_id,run,repo,sha


@pytest.mark.parametrize('build_failed',[False,True])
def test_resume_only_builds_and_deploys_retaining_scan(tmp_path,monkeypatch,build_failed):
    run_id,run,repo,sha=retained(tmp_path)
    original=(run/'security_findings.json').read_bytes(); calls=[]
    obj=LocalOrchestrator(tmp_path,job_id='job',commit_sha=sha,approved_cwes=['CWE-502'],resume_run_id=run_id)
    def execute(**kwargs):
        calls.append(kwargs['step_name']);assert kwargs['repo_dir']==repo
        return StepRunResult('failed' if build_failed else 'success',1 if build_failed else 0,'fixture')
    monkeypatch.setattr(obj,'_execute_step',execute)
    result,path=obj.run('https://github.com/test/repo','main')
    assert path==run and result.run_id==run_id
    assert calls==(['build'] if build_failed else ['build','deploy'])
    assert result.status==('failed' if build_failed else 'success')
    assert result.started_at=='2026-11-16T00:00:00+09:00'
    assert (run/'security_findings.json').read_bytes()==original
    gate=next(s for s in result.steps if s.step_name=='security_gate')
    assert gate.status=='success' and gate.finished_at=='2026-11-16T00:00:01+09:00'


@pytest.mark.parametrize('invalid',['workspace','commit','approval','missing'])
def test_resume_rejects_changed_or_unapproved_workspace(tmp_path,monkeypatch,invalid):
    run_id,run,repo,sha=retained(tmp_path)
    if invalid=='workspace':(repo/'source.txt').write_text('changed')
    if invalid=='missing':(repo/'source.txt').unlink()
    obj=LocalOrchestrator(tmp_path,job_id='job',commit_sha='b'*40 if invalid=='commit' else sha,
        approved_cwes=[] if invalid=='approval' else ['CWE-502'],resume_run_id=run_id)
    monkeypatch.setattr(obj,'_execute_step',lambda **kwargs:pytest.fail('must not build or deploy'))
    with pytest.raises(RuntimeError):obj.run('https://github.com/test/repo','main')


def test_legacy_workspace_allows_build_executable_bit_change(tmp_path,monkeypatch):
    run_id,run,repo,sha=retained(tmp_path)
    (run/'resume_checkpoint.json').unlink()
    (repo/'source.txt').chmod(0o755)
    from app.workflow import WorkflowDefinition,WorkflowStepDefinition
    monkeypatch.setattr('app.workflow.resolve_workflow_definition',lambda **kw:WorkflowDefinition('fixture','node',
        [WorkflowStepDefinition(name=n,kind='builtin',uses=n) for n in ['build','deploy']],'fixture'))
    obj=LocalOrchestrator(tmp_path,job_id='job',commit_sha=sha,approved_cwes=['CWE-502'],selected_items=['CWE-502'],resume_run_id=run_id)
    seen=[]
    monkeypatch.setattr(obj,'_execute_step',lambda **kw: (seen.append(kw['step_name']) or StepRunResult('success',0,'fixture')))
    assert obj.run('https://github.com/test/repo','main')[0].status=='success'
    assert seen==['build','deploy']
