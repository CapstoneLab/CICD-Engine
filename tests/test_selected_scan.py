import json
from types import SimpleNamespace
import yaml
from app.steps import deep_security as deep
from app.orchestrator import LocalOrchestrator
from app.workflow import WorkflowStepDefinition as Step
from app.security_policy import evaluate
from app.scanners.semgrep_parser import parse_semgrep_report


def test_secret_scanner_not_invoked_when_unselected(tmp_path, monkeypatch):
    import app.orchestrator as module
    monkeypatch.setattr(module, 'run_lightweight_security_scan', lambda **kw: (_ for _ in ()).throw(AssertionError('must not scan')))
    obj=LocalOrchestrator(tmp_path, selected_items=['CWE-79'])
    result=obj._execute_builtin_step(Step('secret','builtin','lightweight_security_scan'),tmp_path,tmp_path,tmp_path/'log')
    assert result.status=='skipped'


def test_secret_only_does_not_invoke_semgrep(tmp_path, monkeypatch):
    monkeypatch.setattr(deep, 'resolve_executable', lambda *a: (_ for _ in ()).throw(AssertionError('must not scan')))
    assert deep.run_deep_security_scan(tmp_path,tmp_path/'log',tmp_path/'report',False,['CWE-798']).status=='skipped'


def test_only_selected_rules_are_executed(tmp_path,monkeypatch):
    monkeypatch.setattr(deep,'resolve_executable',lambda _: 'semgrep')
    report=tmp_path/'report.json'
    def run(command, **kw):
        rules=yaml.safe_load(open(command[command.index('--config')+1]))['rules']
        assert rules
        from app.security_catalog import normalize_cwe
        assert all(any(normalize_cwe(c) == 'CWE-79' for c in rule['metadata']['cwe']) for rule in rules)
        report.write_text(json.dumps({'results':[], 'paths':{'scanned':['app.js']}}))
        return SimpleNamespace(exit_code=0,output='')
    monkeypatch.setattr(deep,'run_command',run)
    assert deep.run_deep_security_scan(tmp_path,tmp_path/'log',report,False,['CWE-79']).status=='success'


def test_secondary_cwe_selection_is_not_lost(tmp_path):
    report=tmp_path/'report.json'
    report.write_text(json.dumps({'paths':{'scanned':['a.py']},'results':[{'path':'a.py','start':{'line':1},'extra':{'severity':'ERROR','metadata':{'cwe':['CWE-94','CWE-79']}}}]}))
    _,findings=parse_semgrep_report(report,selected_cwes={'CWE-79'})
    assert findings[0].cwe=='CWE-79'
    assert evaluate(findings,selected_items=['CWE-79']).verdict != 'pass'
