using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioJobConfirmationFactoryTests
{
    [TestMethod]
    public void CreateRecoveryConsent_NamesExactJobCheckpointAndAction()
    {
        var job = CreateJob();
        var cases = new[]
        {
            (
                Action: StudioJobConfirmationAction.Resume,
                Title: "Resume render job \"job-42\"?",
                PrimaryButton: "Resume",
                RequiredMessage: new[]
                {
                    "\"Resume\"",
                    "render job \"job-42\"",
                    "auto-resume this job",
                }),
            (
                Action: StudioJobConfirmationAction.Retry,
                Title: "Retry render job \"job-42\"?",
                PrimaryButton: "Retry",
                RequiredMessage: new[]
                {
                    "\"Retry\"",
                    "render job \"job-42\"",
                    "auto-retry this job",
                }),
            (
                Action: StudioJobConfirmationAction.ResumeFromCheckpoint,
                Title: "Resume saved checkpoint for render job \"job-42\"?",
                PrimaryButton: "Resume from checkpoint",
                RequiredMessage: new[]
                {
                    "\"Resume from checkpoint\"",
                    "saved checkpoint for render job \"job-42\"",
                    "auto-resume this checkpoint",
                }),
            (
                Action: StudioJobConfirmationAction.RestartClean,
                Title: "Restart render job \"job-42\" clean?",
                PrimaryButton: "Restart clean",
                RequiredMessage: new[]
                {
                    "\"Restart clean\"",
                    "saved checkpoint for render job \"job-42\"",
                    "cached frames",
                }),
            (
                Action: StudioJobConfirmationAction.ClearCachedFrames,
                Title: "Clear cached frames for render job \"job-42\"?",
                PrimaryButton: "Clear cached frames",
                RequiredMessage: new[]
                {
                    "\"Clear cached frames\"",
                    "render job \"job-42\"",
                    "delete cached render frames",
                }),
            (
                Action: StudioJobConfirmationAction.DropCheckpoint,
                Title: "Drop saved checkpoint for render job \"job-42\"?",
                PrimaryButton: "Drop checkpoint",
                RequiredMessage: new[]
                {
                    "\"Drop checkpoint\"",
                    "saved checkpoint for render job \"job-42\"",
                    "later recovery or continuation",
                }),
        };

        foreach (var testCase in cases)
        {
            StudioActionConfirmation prompt =
                StudioJobConfirmationFactory.CreateRecoveryConsent(job, testCase.Action);

            Assert.AreEqual(testCase.Title, prompt.Title, $"Unexpected title for {testCase.Action}.");
            Assert.AreEqual(testCase.PrimaryButton, prompt.PrimaryButtonText, $"Unexpected button text for {testCase.Action}.");
            foreach (string fragment in testCase.RequiredMessage)
            {
                StringAssert.Contains(prompt.Message, fragment, $"Missing message fragment for {testCase.Action}: {fragment}");
            }
        }
    }

    [TestMethod]
    public void CreateRecoveryConsent_FallsBackToGenericJobLabelWhenTypeIsMissing()
    {
        var job = CreateJob(type: " ");

        StudioActionConfirmation prompt =
            StudioJobConfirmationFactory.CreateRecoveryConsent(job, StudioJobConfirmationAction.Resume);

        Assert.AreEqual("Resume job \"job-42\"?", prompt.Title);
        StringAssert.Contains(prompt.Message, "job \"job-42\"");
    }

    private static StudioJob CreateJob(string type = "render") => new(
        Id: "job-42",
        ProjectId: "project-9",
        Type: type,
        Status: "paused",
        CreatedAt: "2026-08-19T23:59:30Z",
        UpdatedAt: "2026-08-20T00:01:00Z",
        StartedAt: "2026-08-20T00:00:00Z",
        FinishedAt: null,
        Error: null,
        Progress: null,
        Result: null,
        Payload: null,
        Attempt: 2);
}
