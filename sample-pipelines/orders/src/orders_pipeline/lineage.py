"""Declared model dependencies and artifact provenance, without SQL, rows or connection strings."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import NAMESPACE_URL, uuid5

PRODUCER = 'https://github.com/RJ1899157/PipeGuard'
SCHEMA = 'https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent'


def _event(run_id, attempt, step, state, when, inputs, outputs, gaps, hashes):
    run_uuid = str(uuid5(NAMESPACE_URL, json.dumps([run_id, attempt, step])))
    return {'basis':'declared_dbt','coverage':'partial' if gaps else 'complete',
            'missing_metadata':sorted(set(gaps)), 'artifact_hashes':hashes, 'expected_steps':[],
            'event':{'eventTime':when,'eventType':state,'producer':PRODUCER,'schemaURL':SCHEMA,
                     'run':{'runId':run_uuid},'job':{'namespace':'local-orders','name':step},
                     'inputs':inputs,'outputs':outputs}}


def gap(run_id, attempt, reason='artifacts_unavailable'):
    return [_event(run_id,attempt,'orders-pipeline','OTHER',datetime.now(timezone.utc).isoformat(),[],[],[reason],{})]


def _dataset(node):
    if node.get('database') != 'sample_warehouse' or node.get('config',{}).get('materialized') == 'ephemeral':
        raise ValueError('unsupported resource')
    name = node['schema'] + '.' + (node.get('identifier') or node.get('alias') or node['name'])
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}',name):
        raise ValueError('unsupported identity')
    return {'namespace':'postgresql://local/sample_warehouse','name':name}


def extract(artifacts, run_id, attempt, summary=None, prefix=''):
    try:
        paths={name:artifacts/(name+'.json') for name in ('manifest','run_results')}
        if any(p.stat().st_size>20_000_000 for p in paths.values()):
            return gap(run_id,attempt,'adapter_limit')
        raw={name:p.read_bytes() for name,p in paths.items()}
        manifest,results=(json.loads(raw[name]) for name in ('manifest','run_results'))
        invocation=manifest['metadata']['invocation_id']
        if not invocation or invocation!=results['metadata']['invocation_id']:
            return gap(run_id,attempt,'artifact_mismatch')
        hashes={name:sha256(content).hexdigest() for name,content in raw.items()}
        nodes=manifest['nodes']|manifest['sources']
        actual={r['unique_id']:r for r in results['results']}
        if len(actual)!=len(results['results']):
            return gap(run_id,attempt,'incomplete_results')
        models={key:node for key,node in manifest['nodes'].items() if node['resource_type']=='model'}
        if not models or len(models)>30:
            return gap(run_id,attempt,'adapter_limit')
        entries=[]
        for key,node in sorted(models.items()):
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:/+\-]{0,254}',key):
                return gap(run_id,attempt,'unsupported_resource')
            gaps=[];inputs=[]
            for parent in node.get('depends_on',{}).get('nodes',[]):
                if parent not in nodes:
                    gaps.append('unresolved_dependency');continue
                try:inputs.append(_dataset(nodes[parent]))
                except (ValueError,KeyError):gaps.append('unsupported_resource')
            try:outputs=[_dataset(node)]
            except (ValueError,KeyError):outputs=[];gaps.append('unsupported_resource')
            inputs = [dict(namespace=namespace,name=name) for namespace,name in sorted({(d['namespace'],d['name']) for d in inputs})]
            if len(inputs)>32:
                inputs=inputs[:32];gaps.append('adapter_limit')
            result=actual.get(key,{})
            state={'success':'COMPLETE','error':'FAIL','fail':'FAIL'}.get(result.get('status'),'OTHER')
            timings=result.get('timing',[])
            if not timings or state=='OTHER':gaps.append('incomplete_results')
            start=timings[0].get('started_at') if timings else None
            end=timings[-1].get('completed_at') if timings else None
            fallback=results['metadata']['generated_at']
            # Validate timestamps locally; invalid metadata becomes a gap instead of unbounded retries.
            for when in (start or fallback,end or fallback):
                value=datetime.fromisoformat(when.replace('Z','+00:00'))
                if value.tzinfo is None:raise ValueError('timezone required')
            if start and state!='OTHER':
                entries.append(_event(run_id,attempt,key,'START',start,inputs,outputs,gaps,hashes))
            entries.append(_event(run_id,attempt,key,state,end or fallback,inputs,outputs,gaps,hashes))
        if summary and summary.get('load_started_at') and summary.get('load_finished_at'):
            source=[{'namespace':'file://orders-pipeline','name':'orders-input'}]
            target=[_dataset({'database':'sample_warehouse','schema':prefix+'raw','name':'orders'})]
            for state,when in [('START',summary['load_started_at']),('COMPLETE',summary['load_finished_at'])]:
                item=_event(run_id,attempt,'orders-loader',state,when,source,target,[],{})
                item['basis']='producer_reported';entries.append(item)
        expected = [{'namespace':'local-orders','name':name} for name in sorted(
            set(models) | ({'orders-loader'} if summary and summary.get('load_finished_at') else set()))]
        for entry in entries:
            entry['expected_steps'] = expected
        return entries
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return gap(run_id,attempt,'invalid_artifacts')
