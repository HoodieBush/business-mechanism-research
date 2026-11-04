"""New registered continuation allocation; never reopen reviewed runs."""
from .closeout import CloseoutWorkspace
from .composed_world import create_world
from .continuation import prepare
from .run import main
from .runtime_closeout import CloseoutRuntime

if __name__ == '__main__':
    raise SystemExit(main(CloseoutWorkspace, CloseoutRuntime, create_world, prepare))
