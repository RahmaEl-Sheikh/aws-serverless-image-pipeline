"""Generates docs/architecture.png  (pip install diagrams; requires Graphviz)."""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import SNS, SQS, StepFunctions
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import APIGateway, CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import Users
from diagrams.programming.language import Python

graph_attr = {"fontsize": "22", "pad": "0.6", "nodesep": "0.7", "ranksep": "1.0", "splines": "spline"}
node_attr = {"fontsize": "12"}

with Diagram(
    "Serverless Image Processing Pipeline",
    filename="docs/architecture",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    users = Users("Users\n(browser)")

    with Cluster("Edge"):
        cdn = CloudFront("CloudFront\n(OAC, HTTPS)")

    with Cluster("API layer"):
        api = APIGateway("HTTP API\nPOST /uploads\nGET /images")
        presign = Lambda("UploadUrl\n(pre-signed POST)")
        read_api = Lambda("ImagesApi\n(list / status)")

    with Cluster("Ingestion & decoupling"):
        source = S3("Source bucket\nuploads/  (lifecycle 30d)")
        queue = SQS("Upload queue")
        dlq = SQS("Dead-letter queue\n(maxReceive 3)")
        dispatcher = Lambda("Dispatcher\n(idempotent)")

    with Cluster("Step Functions - Standard workflow"):
        sfn = StepFunctions("Image pipeline")
        validate = Lambda("Validate")
        with Cluster("Parallel"):
            resize = Lambda("Resize\n(thumbnail)")
            watermark = Lambda("Watermark\n(full-res)")
            meta = Lambda("Extract\nmetadata")
        layer = Python("Pillow\nLambda Layer")

    with Cluster("Storage & catalogue"):
        processed = S3("Processed bucket\nimages/  (IA -> Glacier IR)")
        web = S3("Web bucket\n(static frontend)")
        table = Dynamodb("Images table\nGSI byStatus")

    with Cluster("Notifications & monitoring"):
        sns = SNS("SNS topic\n(success / failure)")
        cw = Cloudwatch("CloudWatch\nalarms + dashboard")

    users >> Edge(label="1  request upload URL") >> api
    api >> presign >> Edge(style="dashed") >> table
    users >> Edge(label="2  POST image (pre-signed)", color="darkorange") >> source
    source >> Edge(label="3  ObjectCreated event") >> queue
    queue >> Edge(label="4  poll (batch 10)") >> dispatcher
    queue >> Edge(style="dashed", color="firebrick", label="failed x3") >> dlq
    dispatcher >> Edge(label="5  StartExecution") >> sfn
    sfn >> validate
    sfn >> resize
    sfn >> watermark
    sfn >> meta
    layer - Edge(style="dotted") - [resize, watermark]
    [resize, watermark] >> Edge(label="6  write renditions") >> processed
    sfn >> Edge(label="7  status + metadata (SDK integration)") >> table
    sfn >> Edge(label="8  publish") >> sns
    users >> Edge(label="9  view gallery", color="darkgreen") >> cdn
    cdn >> [web, processed]
    api >> read_api >> table
    [dlq, sfn] >> Edge(style="dotted") >> cw >> Edge(style="dotted") >> sns
