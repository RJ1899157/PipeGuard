"""Explicitly require complete declared lineage for newly observed executions of one job."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/pipeguard/src'))
from pipeguard.detection.airflow import NoRedirect
from pipeguard.lineage.contracts import ExpectationCreate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id',required=True)
    parser.add_argument('--grace-seconds',type=int,default=300)
    body=ExpectationCreate(**vars(parser.parse_args())).model_dump(mode='json')
    headers={'Authorization':'Bearer '+os.environ['PIPEGUARD_ADMIN_TOKEN'],'Content-Type':'application/json'}
    opener=build_opener(ProxyHandler({}),NoRedirect())
    try:
        with opener.open(Request('http://127.0.0.1:8000/v1/lineage-expectations',headers=headers,
                                 data=json.dumps(body).encode()),timeout=5) as r:
            assert r.status==201
    except HTTPError as error:
        if error.code!=409:raise RuntimeError('enrollment_failed') from None
        with opener.open(Request('http://127.0.0.1:8000/v1/jobs/'+body['job_id']+'/lineage-expectation',headers=headers),timeout=5) as r:
            row=json.load(r)
        if any(row.get(k)!=v for k,v in body.items()):raise RuntimeError('existing_expectation_differs')
    print('Lineage delivery expectation enrolled or matching expectation verified')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Lineage enrollment failed (private details withheld)')
