from typing import Literal
from ..paired_v02.workspace import TOOLS as PreviousTools
from ..paired_v01.contracts import Response,SearchMemory as PreviousSearch,schemas

class SearchMemory(PreviousSearch):
    kind: Literal['all','hypothesis','plan','result','assessment','state','process','card','knowledge',
                  'review','review_response','report_draft','report']='all'

TOOLS={**PreviousTools,
       'search_memory':(SearchMemory,'检索科学档案、历史、审查意见与研究者回应；可检索不等于可作为事实前提。'),
       'respond_to_review':(Response,'单独回应一条完整核验意见：accept/revise/rebut/defer、理由、原证据和替代对象。无需重填研究状态；不自动修复对象或关闭争议。')}
