"""Reuse a retained scan/workspace; never execute clone or scanners on resume."""
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict
from pathlib import Path
from app.models import PipelineRun, PipelineStep, SecurityFinding, now_iso
from app.security_policy import evaluate, is_blocking
from app.utils.filesystem import data_root, save_json
from app.workflow import WorkflowStepDefinition


def workspace_digest(repo):
    names=subprocess.check_output(['git','-c','safe.directory='+str(repo.resolve()),'ls-files','-z','--cached','--others','--exclude-standard'],cwd=repo).split(b'\0')
    digest=hashlib.sha256()
    for name in sorted(set(n for n in names if n)):
        path=repo/os.fsdecode(name)
        digest.update(name+b'\0')
        if path.is_symlink(): digest.update(os.readlink(path).encode())
        elif path.is_file(): digest.update(path.read_bytes())
        else: digest.update(b'<missing>')
    return digest.hexdigest()


def save_checkpoint(obj, run_dir, repo_dir, workflow):
    save_json(run_dir/'resume_checkpoint.json', {'job_id':obj._job_id,'commit_sha':obj._scanned_commit_sha,
        'workspace_digest':workspace_digest(repo_dir), 'selected_items':obj._effective_selected_items,
        'steps':[asdict(s) for s in workflow.steps if s.name in {'build','deploy'}]})


def resume_run(obj, repo_url, branch, workflow_path):
    run_id=obj._resume_run_id
    if not re.fullmatch(r'run-\d{8}-\d+',run_id): raise RuntimeError('Invalid resume workspace identifier')
    root=data_root(obj.base_dir); run_dir=root/'runs'/run_id;repo=root/'workspace'/run_id/'repo'
    if not repo.is_dir(): raise RuntimeError('Retained workspace is missing; a new scan is required')
    original=json.loads((run_dir/'pipeline_result.json').read_text())
    callback=json.loads((run_dir/'callback_result.json').read_text())
    verdict=json.loads((run_dir/'security_verdict.json').read_text())
    if callback.get('job_id')!=obj._job_id or original['repo_url']!=repo_url or original['branch']!=branch:
        raise RuntimeError('Resume workspace does not belong to this job/repository/branch')
    sha=subprocess.check_output(['git','-c','safe.directory='+str(repo.resolve()),'rev-parse','HEAD'],cwd=repo,text=True).strip()
    if not obj._commit_sha or sha!=obj._commit_sha or verdict.get('scanned_commit_sha')!=sha:
        raise RuntimeError('Retained workspace does not match the approved scan commit')
    if original['status']!='failed' or verdict.get('verdict')!='block_pending_approval':
        raise RuntimeError('This workspace is not paused at an approval gate')
    checkpoint=run_dir/'resume_checkpoint.json'
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text())
        if saved['job_id']!=obj._job_id or saved['commit_sha']!=sha or saved['workspace_digest']!=workspace_digest(repo):
            raise RuntimeError('Workspace changed after security scan; a new scan is required')
        definitions=[WorkflowStepDefinition(**s) for s in saved['steps']]
        obj._effective_selected_items=saved['selected_items']
    else:
        # Compatibility for retained runs produced before checkpoint support.
        if subprocess.run(['git','-c','safe.directory='+str(repo.resolve()),'-c','core.fileMode=false','diff','--no-ext-diff','--no-textconv','--quiet','HEAD','--'],cwd=repo).returncode:
            raise RuntimeError('Legacy workspace has tracked modifications; a new scan is required')
        from app.workflow import resolve_workflow_definition
        workflow=resolve_workflow_definition(repo_dir=repo,base_dir=obj.base_dir,workflow_path=workflow_path)
        definitions=[s for s in workflow.steps if s.name in {'build','deploy'}]
        obj._effective_selected_items=obj._selected_items_override
    if [s.name for s in definitions]!=['build','deploy']:
        raise RuntimeError('Retained workflow must have build then deploy stages')
    findings=[SecurityFinding(**f) for f in json.loads((run_dir/'security_findings.json').read_text())]
    obj._scanned_commit_sha=sha
    obj._security_verdict=evaluate(findings,selected_items=obj._effective_selected_items,
        environment=obj._environment,approved_cwes=obj._approved_cwes,scanned_commit_sha=sha)
    if is_blocking(obj._security_verdict): raise RuntimeError('Approval does not cover the retained blocking findings')
    obj._gate_findings=[{'severity':f.severity,'cwe':f.cwe,'scanner_name':f.scanner_name.lower(),'in_scope':f.in_scope} for f in findings]
    steps=[PipelineStep(**s) for s in original.pop('steps')]
    run=PipelineRun(**original,steps=steps)
    gate=next(s for s in steps if s.step_name=='security_gate')
    gate.status='success';gate.exit_code=0;gate.summary_message=obj._approval_note or 'Approved'
    for step in steps:
        if step.step_name in {'build','deploy'}:
            step.status='pending';step.started_at=None;step.finished_at=None;step.exit_code=None;step.summary_message=None
    run.status='running';run.finished_at=None
    obj._current_runtime_type=run.runtime_type
    obj._write_pipeline_result(run_dir,run)
    save_json(run_dir/'security_verdict.json',obj._security_verdict.to_dict())
    for index,definition in enumerate(definitions):
        step=next(s for s in steps if s.step_name==definition.name)
        result=obj._run_and_record_step(run,step,repo_url,branch,repo,run_dir,run_dir/'logs',definition)
        if result.status=='failed':
            obj._mark_remaining_steps_skipped(run,[s for s in steps if s.step_name in [d.name for d in definitions[index+1:]]],
                'Skipped because resumed build failed',run_dir,repo_url,branch)
            run.status='failed';break
    else:run.status='success'
    run.finished_at=now_iso();run.current_step=None
    obj._write_pipeline_result(run_dir,run)
    return run,run_dir
