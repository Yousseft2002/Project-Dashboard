import argparse
from collector import DEFAULT_CONFIG, read_json
from .service import run
from .security import text

def main():
    parser=argparse.ArgumentParser(description='Project Dashboard Agent')
    parser.add_argument('command',choices=('run','preview','diagnostics'),nargs='?',default='run')
    parser.add_argument('--config',default=str(DEFAULT_CONFIG)); parser.add_argument('--once',action='store_true')
    parser.add_argument('--local-development',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='diagnostics':
            from pathlib import Path
            print(__import__('json').dumps(read_json(Path(args.config).parent/'data/agent/diagnostics.json'),indent=2))
        else: run(args.config,args.once,args.command=='preview',args.local_development)
        return 0
    except Exception as error:
        print('Project Dashboard Agent: '+text(error)); return 1

if __name__=='__main__': raise SystemExit(main())
