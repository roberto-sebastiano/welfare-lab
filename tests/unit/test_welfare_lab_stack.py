import aws_cdk as core
import aws_cdk.assertions as assertions

from welfare_lab.welfare_lab_stack import WelfareLabStack

# example tests. To run these tests, uncomment this file along with the example
# resource in welfare_lab/welfare_lab_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = WelfareLabStack(app, "welfare-lab")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
