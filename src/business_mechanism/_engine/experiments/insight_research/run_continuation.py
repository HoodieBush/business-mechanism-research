from .run import main
from .continuation import ContinuationWorkspace, prepare
from .runtime_continuation import ContinuationRuntime
from .composed_world import create_world

if __name__ == '__main__':
    raise SystemExit(main(ContinuationWorkspace, ContinuationRuntime, create_world, prepare))
