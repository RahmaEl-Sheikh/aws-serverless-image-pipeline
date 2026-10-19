"""Generates docs/architecture.png  (pip install diagrams; requires Graphviz).

Layout is kept compact (few columns) with large fonts so the diagram stays
readable when GitHub scales it down to the README width.
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import SNS, SQS, StepFunctions
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import APIGateway, CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import Users

FONT = "Helvetica-Bold"

graph_attr = {
    "fontsize": "44", "fontname": FONT, "labelloc": "t",
    "pad": "0.4", "nodesep": "0.6", "ranksep": "1.0",
    "splines": "spline", "dpi": "130",
}
# diagrams sets each node's height (1.9in for a one-line label); keeping the
# icon 1.4in wide and pinned to the top leaves room for the label underneath.
node_attr = {"fontsize": "22", "fontname": FONT, "width": "1.4",
             "imagescale": "true", "imagepos": "tc", "labelloc": "b", "fixedsize": "true"}
edge_attr = {"fontsize": "26", "fontname": FONT, "penwidth": "3.5", "arrowsize": "1.6", "color": "#3b4252"}
cluster = {"fontsize": "28", "fontname": FONT, "margin": "22", "penwidth": "2"}


def step(n, **extra):
    return Edge(label=f"  {n}  ", fontcolor="#c2410c", fontsize="34", fontname=FONT, **extra)


with Diagram(
    "Serverless Image Processing Pipeline",
    filename="docs/architecture",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
):
    users = Users("Users")

    with Cluster("API", graph_attr=cluster):
        api = APIGateway("API Gateway")
        upload_fn = Lambda("Upload URL")

    with Cluster("Ingestion", graph_attr=cluster):
        source = S3("Source S3")
        queue = SQS("SQS Queue")
        dlq = SQS("DLQ")

    dispatcher = Lambda("Dispatcher")

    with Cluster("Step Functions Workflow", graph_attr=cluster):
        sfn = StepFunctions("State Machine")
        validate = Lambda("Validate")
        with Cluster("Parallel", graph_attr=cluster):
            resize = Lambda("Resize")
            watermark = Lambda("Watermark")
            meta = Lambda("Metadata")

    with Cluster("Storage", graph_attr=cluster):
        processed = S3("Processed S3")
        table = Dynamodb("DynamoDB")

    with Cluster("Delivery & Alerts", graph_attr={**cluster, "labelloc": "b"}):
        cdn = CloudFront("CloudFront")
        sns = SNS("SNS")
        cw = Cloudwatch("CloudWatch")

    users >> step(1, headport="w") >> api >> upload_fn
    users >> step(2) >> source
    source >> step(3) >> queue
    queue >> Edge(style="dashed", color="#b91c1c") >> dlq
    queue >> step(4, headport="w") >> dispatcher
    dispatcher >> step(5) >> sfn
    sfn >> validate
    validate >> [resize, watermark, meta]
    [resize, watermark] >> step(6) >> processed
    sfn >> step(7) >> table
    sfn >> step(8, headport="n", labelangle="0") >> sns
    dlq >> Edge(style="dotted") >> cw
    cw >> Edge(style="dotted") >> sns
    processed >> step(9) >> cdn
    cdn >> Edge(color="#15803d") >> users
