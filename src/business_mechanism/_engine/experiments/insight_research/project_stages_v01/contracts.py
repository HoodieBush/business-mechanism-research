from ..stage_delivery_v01.contracts import TOOLS as Previous,schemas as base_schemas
from ..fresh_retail_v02.contracts import Review
from ..open_retail_v12.contracts import REVIEW_TOOLS as PeerPrevious
class Search(Previous['search_memory'][0]):
    archive_stage:str|None=None
class PeerSearch(PeerPrevious['search_memory'][0]):
    archive_stage:str|None=None
TOOLS={**Previous,'search_memory':(Search,Previous['search_memory'][1]+' Optional archive_stage searches an explicitly received earlier stage with historical lifecycle and full original access. No automatic promotion to current facts.')}
REVIEW_TOOLS={**PeerPrevious,'search_memory':(PeerSearch,PeerPrevious['search_memory'][1]+' Optional archive_stage gives the same lawful project history as the researcher, without their private thoughts.')}
def schemas(toolset=TOOLS):return base_schemas(toolset)
