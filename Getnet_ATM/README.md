# Team repository: AWS M&E Agentic AI Partner Hackathon

This repository lives in **AWS CodeCommit in your team's AWS account**. Your Kiro IDE in
the browser already has it cloned in `/workshop`, so you can start right away.

## Working as a team

One Kiro IDE is shared by everyone in your team. To avoid overwriting each other:

- **One person, one branch.** `git switch -c <your-name>` before you start, and merge
  into `main` when a piece works.
- **One Kiro chat per person**, each on a different part of the project. Two agents
  editing the same files at the same time will overwrite each other's changes.
- **Parallel work in the terminal:** open a new terminal and run `kiro-cli chat`. It is
  already signed in.
- **Push often:** `git push -u origin <your-name>`. Teammates on their own laptops can
  clone the same repo with `git-remote-codecommit`
  (`git clone codecommit::us-east-2://hackathon-team`).

## Start here

1. Fill in [`TEAM.md`](TEAM.md) during the *Before you build* session. Your final pitch
   is built from it.
2. Pick a use case (see the workshop guide, *Sample Use Cases*), or bring your own.
3. Tell Kiro what you are building. The steering file in `.kiro/steering/` already gives
   it the hackathon context.

## Where things are

| What | Where |
|---|---|
| Sample videos and the Audience 360 dataset | Your team's S3 bucket: see `HackathonAssetsBucketName`, `TestVideosURI` and `AudienceDataURI` in **Event Outputs** |
| AWS region | **`us-east-1`** for Bedrock and AWS services (already set as `AWS_REGION`). The IDE, this repo and ComfyUI run in `us-east-2` |
| Videos for Bedrock (Pegasus, Marengo) | The toolkit bucket `MediaToolkitIngestBucket` (us-east-1), same sample videos |
| AWS documentation and APIs for your agent | The Agent Toolkit for AWS is pre-installed in the browser IDE |

Never commit API keys or credentials. Use environment variables or AWS Secrets Manager.

The team account, and this repository with it, is deleted when the event ends. Push
anything you want to keep to your own Git provider before you leave.
