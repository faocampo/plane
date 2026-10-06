"""Disposable DDL authoring experiment, always rolled back; never grants a pin."""
import django
django.setup()
from django.db import connection,transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations import RunPython
from importlib import import_module
import json
m=import_module('plane.curve.migrations.0025_manual_gate2_reconstruction')
executor=MigrationExecutor(connection);state=executor.loader.project_state([('curve','0024_manual_draft_reconstruction')])
with transaction.atomic():
 with connection.cursor() as c:
  assert m._catalog(c)==m.BASELINE_CATALOG_DIGEST
  c.execute('SELECT curve_scope_reopening_verify_coverage()')
 with connection.schema_editor() as editor:
  for op in m.Migration.operations:
   previous=state.clone();op.state_forwards('curve',state)
   if not isinstance(op,RunPython):op.database_forwards('curve',editor,previous,state)
 with connection.cursor() as c:
  catalog=m._catalog(c)

  print(json.dumps(dict(status='ROLLED_BACK_DDL_EXPERIMENT',physical_catalog_digest=catalog)),flush=True)
 transaction.set_rollback(True)
with transaction.atomic(), connection.cursor() as c:
 assert m._catalog(c)==m.BASELINE_CATALOG_DIGEST
 c.execute('SELECT curve_scope_reopening_verify_coverage()')
 print('Original catalog restored and verified',flush=True)
