"""Export the exact installed role prompts for inspection, without model calls."""
import argparse
import hashlib
import json
from pathlib import Path
from business_mechanism import __version__
from business_mechanism.prompts import compose

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
hashes={}
for role in ('researcher','critic'):
    value=compose(role);path=args.output/(role+'.txt');path.write_text(value,encoding='utf-8')
    hashes[role]=hashlib.sha256(value.encode()).hexdigest()
(args.output/'manifest.json').write_text(json.dumps({'version':__version__,'sha256':hashes,'model_calls':0},indent=2)+'\n')
print(json.dumps({'output':str(args.output),'sha256':hashes,'model_calls':0}))
