"""Record the real pinned Git >8MB refusal and short presentation, not heldout quality."""
from pathlib import Path
import json,subprocess
from unittest.mock import patch
from agent_graph import core_identity
from agent_service.core_analyzer import CoreAnalyzer
from agent_service.analysis import view_from_result
from agent_service.jira_presentation import summary_doc
from tests.service.test_resource_limits import ResourceLimitsTests
root=Path.cwd();target=root/'work/batch05-defaults/default-refusal.json';assert not target.exists()
case=ResourceLimitsTests('test_default_eight_megabyte_budget_counts_repeated_git_blobs_and_refuses');case.setUp();captured={};original=CoreAnalyzer.analyze
try:
 def observe(self,request,**kwargs):
  result=original(self,request,**kwargs);captured.update(request=request,result=result)
  return result
 with patch.object(CoreAnalyzer,'analyze',observe):case.test_default_eight_megabyte_budget_counts_repeated_git_blobs_and_refuses()
 view=view_from_result(captured['result'],captured['request'])
 captured.update(provenance='authored_resource_refusal_fixture_not_quality_case',short_comment=summary_doc(view,captured['result'],kind='pr',gaps=[],earlier=[]),
  selected_added_files=140,added_bytes=140*60_000,core_identity=core_identity(),source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),partial_context_saved=False)
 target.write_text(json.dumps(captured,indent=2)+'\n');print(json.dumps(dict(status='PASS',reason=captured['result']['reason_code'],summary=captured['result']['summary'])))
finally:case.doCleanups()
