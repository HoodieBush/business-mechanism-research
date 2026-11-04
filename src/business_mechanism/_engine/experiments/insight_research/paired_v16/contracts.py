from pydantic import Field
from ..contracts import Input
from ..paired_v11.contracts import TOOLS as PreviousTools, REVIEW_TOOLS, schemas


class RequestReview(Input):
    job_ref: str
    reason: str = Field(min_length=1)


TOOLS = {**PreviousTools,
    'request_review': (RequestReview, '显式安排一个待审对象的核验。self先安排再用review_claim提交；independent由独立质疑者核验。保存判断不自动抢占研究。已付费核验优先排空，意见后由研究者回应。')}
