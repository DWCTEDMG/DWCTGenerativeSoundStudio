using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class PostProductionContractsTests
{
    [TestMethod]
    public void Schema_RoundTripsExtensionsExactSamplesAndValidatesReferences()
    {
        CanonicalProject project = Project("\"post\":{\"schema_version\":1,\"vendor\":{\"deep\":true},\"sync_anchors\":[{\"id\":\"sync\",\"method\":\"clap\",\"clip_id\":\"clip\",\"offset_samples\":\"-9007199254740993\",\"confidence\":0.9,\"extension\":{\"x\":1}}],\"adr_cues\":[],\"reconform_history\":[],\"interchange_history\":[],\"audio_layouts\":[]}");
        PostProductionDocument document = PostProductionContracts.Read(project.Timeline);

        Assert.AreEqual(-9_007_199_254_740_993L, document.SyncAnchors[0].OffsetSamples);
        JsonObject written = PostProductionContracts.Write(project.Timeline, document);
        Assert.AreEqual("-9007199254740993", written["post"]!["sync_anchors"]![0]!["offset_samples"]!.GetValue<string>());
        Assert.IsTrue(written["post"]!["vendor"]!["deep"]!.GetValue<bool>());
        Assert.AreEqual(1, written["post"]!["sync_anchors"]![0]!["extension"]!["x"]!.GetValue<int>());
        var extensionEdit = new ReconformEdit(ReconformEditKind.Insert, 10, 10, 10, 20,
            new JsonObject { ["vendor_edit"] = new JsonObject { ["enabled"] = true } });
        PostProductionDocument withHistory = document with
        {
            ReconformHistory = [new("history", "2026-01-01T00:00:00Z", [extensionEdit], new JsonObject())]
        };
        JsonObject historyRoundTrip = PostProductionContracts.Write(project.Timeline,
            PostProductionContracts.Read(PostProductionContracts.Write(project.Timeline, withHistory)));
        Assert.IsTrue(historyRoundTrip["post"]!["reconform_history"]![0]!["edits"]![0]!["vendor_edit"]!["enabled"]!.GetValue<bool>());
        Assert.Throws<InvalidDataException>(() => PostProductionContracts.Read(JsonNode.Parse("{\"post\":{\"schema_version\":2}}")!.AsObject()));
        Assert.IsNull(new JsonObject()["post"]);
        Assert.IsEmpty(PostProductionContracts.Read(new JsonObject()).AdrCues);
        Assert.Throws<InvalidDataException>(() => Project("\"post\":{\"schema_version\":1,\"sync_anchors\":[{\"id\":\"s\",\"method\":\"clap\",\"clip_id\":\"missing\",\"offset_samples\":\"0\",\"confidence\":1}]}") );
    }

    [TestMethod]
    public void Timecode_DropFrameAndSamplesRoundTrip()
    {
        FrameRate rate = new(30_000, 1_001);
        Timecode tc = Timecode.Parse("01:00:00;00", rate);
        Assert.AreEqual(107_892L, tc.FrameNumber);
        Assert.AreEqual("01:00:00;00", tc.ToString());
        Assert.Throws<FormatException>(() => Timecode.Parse("00:01:00;00", rate));
        Assert.Throws<ArgumentException>(() => Timecode.Parse("00:00:00;00", new FrameRate(25, 1)));
        var timebase = new ProjectTimebase(48_000, rate, true, "01:00:00;00");
        TimelinePosition position = timebase.FromTimecode("01:00:10;00");
        Assert.AreEqual("01:00:10;00", timebase.ToTimecode(position).ToString());
        Assert.AreEqual(position, timebase.FromFrame(timebase.ToFrame(position)));
        CanonicalProject project = Project("\"timebase\":{\"sample_rate\":48000,\"frame_rate\":{\"numerator\":30000,\"denominator\":1001},\"drop_frame\":true,\"start_timecode\":\"01:00:00;00\"}");
        Assert.AreEqual("01:00:00;00", ProjectTimelineContracts.RebuildTimeline(project)["timebase"]!["start_timecode"]!.GetValue<string>());
        var legacyTimebase = new ProjectTimebase(48_000, new FrameRate(12, 1));
        Assert.AreEqual(12d, legacyTimebase.FrameRate.FramesPerSecond);
        Assert.Throws<ArgumentException>(() => legacyTimebase.ToTimecode(new TimelinePosition(0)));
    }

    [TestMethod]
    public void Alignment_FindsOnsetAndWaveformShiftWithoutFalseAcceptance()
    {
        float[] reference = [0, 0, 1, .2f, -.4f, .8f, -.2f, 0];
        float[] candidate = [0, 0, 0, 1, .2f, -.4f, .8f, -.2f];
        AlignmentResult onset = PostAlignment.StrongestOnset(reference, candidate, SyncMethod.Clap, .1);
        AlignmentResult correlation = PostAlignment.WaveformCorrelation(reference, candidate, 3, .8);
        Assert.AreEqual(1L, onset.OffsetSamples);
        Assert.AreEqual(1L, correlation.OffsetSamples);
        Assert.IsTrue(correlation.Acceptable);
        AlignmentResult insufficient = PostAlignment.WaveformCorrelation([0], [0], 1);
        Assert.IsFalse(insufficient.Acceptable);
        Assert.IsTrue(insufficient.Ambiguous);
    }


    [TestMethod]
    public void SyncSelectionUsesCanonicalWaveformDiscriminator()
    {
        Assert.AreEqual(SyncMethod.WaveformCorrelation,
            PostProductionContracts.ParseSyncSelection("waveform_correlation"));
        Assert.Throws<InvalidDataException>(() => PostProductionContracts.ParseSyncSelection("waveform"));
    }

    [TestMethod]
    public void AdrOperations_ReviewAndPreferredSelectionAreImmutableAndUnique()
    {
        AdrCue cue = new("cue", "clip", 10, 20, "Line", "Actor", [], new JsonObject());
        PostProductionDocument original = AdrOperations.AddCue(PostProductionContracts.Empty(), cue);
        AdrRecordingMetadata recording = new("Actor", "U87", "Input 1", "2026-01-01T00:00:00Z", 48_000, 1, new JsonObject());
        PostProductionDocument withTakes = AdrOperations.RegisterTake(AdrOperations.RegisterTake(original, "cue", new("one", "cue", "asset", AdrReviewStatus.Unreviewed, false, recording, new JsonObject())), "cue", new("two", "cue", "asset", AdrReviewStatus.Unreviewed, false, recording, new JsonObject()));
        PostProductionDocument selected = AdrOperations.ReviewTake(withTakes, "cue", "one", AdrReviewStatus.Approved, true);
        selected = AdrOperations.ReviewTake(selected, "cue", "two", AdrReviewStatus.Approved, true);
        Assert.IsFalse(original.AdrCues[0].Takes.Any());
        Assert.AreEqual("two", selected.AdrCues[0].Takes.Single(take => take.Preferred).Id);
        Assert.Throws<InvalidOperationException>(() => AdrOperations.ReviewTake(selected, "cue", "one", AdrReviewStatus.Rejected, true));
    }

    [TestMethod]
    public void Reconform_PlansConflictsRejectsLockedAndAppliesEveryTimelineDomain()
    {
        ReconformPlan conflict = ReconformService.Plan([new(ReconformEditKind.Insert, 10, 11, 10, 20)]);
        Assert.IsFalse(conflict.CanApply);
        ReconformPlan mismatchedCoordinates = ReconformService.Plan([
            new(ReconformEditKind.Insert, 50, 50, 50, 60),
            new(ReconformEditKind.Delete, 100, 110, 100, 100)
        ]);
        Assert.IsFalse(mismatchedCoordinates.CanApply);
        ReconformPlan plan = ReconformService.Plan([new(ReconformEditKind.Insert, 50, 50, 50, 60)]);
        CanonicalProject project = Project("\"markers\":[{\"id\":\"mark\",\"position_sample\":\"100\"}],\"post\":{\"schema_version\":1,\"sync_anchors\":[{\"id\":\"sync\",\"method\":\"clap\",\"clip_id\":\"clip\",\"offset_samples\":\"100\",\"confidence\":1}],\"adr_cues\":[{\"id\":\"cue\",\"clip_id\":\"clip\",\"start_sample\":\"100\",\"end_sample\":\"110\",\"text\":\"x\",\"takes\":[]}]}" );
        ReconformResult result = ReconformService.Apply(project, PostProductionContracts.Read(project.Timeline), plan);
        Assert.AreEqual(110L, result.Project.Markers[0].Position.Samples);
        Assert.AreEqual(110L, result.Post.AdrCues[0].StartSample);
        Assert.HasCount(1, result.Post.ReconformHistory);
        CanonicalProject deletedProject = Project(string.Empty);
        ReconformPlan delete = ReconformService.Plan([new(ReconformEditKind.Delete, 0, 1000, 0, 0)]);
        Assert.IsEmpty(ReconformService.Apply(deletedProject, PostProductionContracts.Empty(), delete).Project.Tracks[0].Events);
        CanonicalProject locked = project with { Tracks = [project.Tracks[0] with { Locked = true }] };
        Assert.Throws<InvalidOperationException>(() => ReconformService.Apply(locked, PostProductionContracts.Read(project.Timeline), plan));

        TimelineEvent sourcedClip = project.Tracks[0].Events[0] with
        {
            Source = new SourceRange(new SourcePosition(48_000, 1_000), new SourcePosition(48_000, 2_000))
        };
        CanonicalProject sourcedProject = project with { Tracks = [project.Tracks[0] with { Events = [sourcedClip] }] };
        ReconformResult split = ReconformService.Apply(sourcedProject, PostProductionContracts.Read(project.Timeline), plan);
        Assert.HasCount(2, split.Project.Tracks[0].Events);
        Assert.AreEqual(1_050L, split.Project.Tracks[0].Events[1].Source!.Start.Samples);
        Assert.AreEqual(split.Project.Tracks[0].Events[1].Id, split.Post.AdrCues[0].ClipId);
        Assert.AreEqual(split.Project.Tracks[0].Events[1].Id, split.Post.SyncAnchors[0].ClipId);
        PostProductionContracts.ValidateAgainstProject(split.Project, split.Post);
        ReconformPlan trim = ReconformService.Plan([new(ReconformEditKind.Delete, 0, 50, 0, 0)]);
        TimelineEvent trimmed = ReconformService.Apply(sourcedProject, PostProductionContracts.Read(project.Timeline), trim).Project.Tracks[0].Events.Single();
        Assert.AreEqual(1_050L, trimmed.Source!.Start.Samples);
        Assert.AreEqual(950L, trimmed.End.Samples - trimmed.Start.Samples);

        ReconformPlan multiple = ReconformService.Plan([
            new(ReconformEditKind.Insert, 50, 50, 50, 60),
            new(ReconformEditKind.Insert, 200, 200, 210, 220)
        ]);
        ReconformResult multipleResult = ReconformService.Apply(sourcedProject, PostProductionContracts.Read(project.Timeline), multiple);
        Assert.HasCount(3, multipleResult.Project.Tracks[0].Events);
        Assert.AreEqual(1_200L, multipleResult.Project.Tracks[0].Events[2].Source!.Start.Samples);
        Assert.AreEqual(220L, multipleResult.Project.Tracks[0].Events[2].Start.Samples);

        TimelineEvent colliding = sourcedClip with { Id = "clip-reconform-50-right", Start = new(2_000), End = new(3_000) };
        CanonicalProject collisionProject = sourcedProject with
        {
            Tracks = [sourcedProject.Tracks[0] with { Events = [sourcedClip, colliding] }]
        };
        ReconformResult collisionResult = ReconformService.Apply(collisionProject, PostProductionContracts.Empty(), plan);
        Assert.AreEqual(collisionResult.Project.Tracks[0].Events.Count,
            collisionResult.Project.Tracks[0].Events.Select(value => value.Id).Distinct(StringComparer.Ordinal).Count());
        Assert.IsTrue(collisionResult.Project.Tracks[0].Events.Any(value => value.Id == "clip-reconform-50-right-2"));

        CanonicalProject markerCollisionProject = collisionProject with
        {
            Tracks = [collisionProject.Tracks[0] with { Events = [sourcedClip] }],
            Markers = [new TimelineMarker("clip-reconform-50-right", "Collision", new TimelinePosition(1_500), null, new JsonObject())]
        };
        ReconformResult markerCollisionResult = ReconformService.Apply(markerCollisionProject, PostProductionContracts.Empty(), plan);
        Assert.IsTrue(markerCollisionResult.Project.Tracks[0].Events.Any(value => value.Id == "clip-reconform-50-right-2"));

        TimelineEvent beforeMove = sourcedClip with { Id = "before", Start = new(0), End = new(100) };
        TimelineEvent movedClip = sourcedClip with { Id = "moved", Start = new(100), End = new(200) };
        TimelineEvent afterMove = sourcedClip with { Id = "after", Start = new(200), End = new(300) };
        CanonicalProject moveProject = sourcedProject with
        {
            Tracks = [sourcedProject.Tracks[0] with { Events = [beforeMove, movedClip, afterMove] }]
        };
        ReconformPlan move = ReconformService.Plan([new(ReconformEditKind.Move, 100, 200, 500, 600)]);
        IReadOnlyList<TimelineEvent> movedEvents = ReconformService.Apply(moveProject, PostProductionContracts.Empty(), move).Project.Tracks[0].Events;
        Assert.AreEqual(100L, movedEvents.Single(value => value.Id == "before").End.Samples);
        Assert.AreEqual(500L, movedEvents.Single(value => value.Id == "moved").Start.Samples);
        Assert.AreEqual(200L, movedEvents.Single(value => value.Id == "after").Start.Samples);

        PostProductionDocument orphanedAnchor = PostProductionContracts.Empty() with
        {
            SyncAnchors = [new("orphan", SyncMethod.Clap, "clip", null, 25, 1, new JsonObject())]
        };
        ReconformPlan deleteAnchor = ReconformService.Plan([new(ReconformEditKind.Delete, 0, 50, 0, 0)]);
        Assert.IsEmpty(ReconformService.Apply(sourcedProject, orphanedAnchor, deleteAnchor).Post.SyncAnchors);
        PostProductionDocument negativeAnchor = orphanedAnchor with
        {
            SyncAnchors = [orphanedAnchor.SyncAnchors[0] with { OffsetSamples = -25 }]
        };
        ReconformPlan deleteClip = ReconformService.Plan([new(ReconformEditKind.Delete, 0, 1000, 0, 0)]);
        Assert.IsEmpty(ReconformService.Apply(sourcedProject, negativeAnchor, deleteClip).Post.SyncAnchors);
    }

    [TestMethod]
    public void Interchange_ReportsLossAndCapabilitiesAreStereoOnly()
    {
        CanonicalProject project = Project(string.Empty);
        AudioLayoutDescriptor layout = new("object-bed", AudioChannelLayout.Object, 2, "asset", [new("obj", "asset", 0, 0, 1, new JsonObject())], new JsonObject { ["vendor"] = true });
        PostProductionDocument document = PostProductionContracts.Empty() with { AudioLayouts = [layout] };
        InterchangeResult<string> canonical = PostProductionInterchange.ExportCanonical(document);
        PostProductionDocument restored = PostProductionInterchange.ImportCanonical(canonical.Value).Value;
        Assert.IsTrue(restored.AudioLayouts[0].Metadata["vendor"]!.GetValue<bool>());
        PostProductionOperationGate previewGate = PostProductionCapabilities.Gate(restored, PostProductionOperation.Preview);
        Assert.IsFalse(previewGate.Allowed);
        StringAssert.Contains(previewGate.Explanation, "metadata-only canonical JSON");
        Assert.IsTrue(PostProductionCapabilities.Gate(PostProductionContracts.Empty(), PostProductionOperation.Render).Allowed);
        Assert.Throws<InvalidOperationException>(() => PostProductionInterchange.ExportCmx3600(project, document));
        Assert.IsFalse(PostProductionInterchange.ExportCmx3600(project, document, true).Compatibility.IsLossless);
        InterchangeResult<string> csv = PostProductionInterchange.ExportAdrCsv(document);
        Assert.IsFalse(csv.Compatibility.IsLossless);
        Assert.IsTrue(PostProductionInterchangeConsent.RequiresExplicitConsent(csv.Compatibility));
        Assert.IsFalse(PostProductionInterchangeConsent.RequiresExplicitConsent(CompatibilityReport.Compatible));
        using JsonDocument fixture = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "post-production-compatibility-golden.json")));
        JsonElement expectedLayouts = fixture.RootElement.GetProperty("native_audio_layouts");
        Assert.HasCount(expectedLayouts.GetArrayLength(), PostProductionCapabilities.Native);
        foreach (JsonElement expected in expectedLayouts.EnumerateArray())
        {
            AudioLayoutCapability actual = PostProductionCapabilities.Native.Single(value =>
                PostProductionContracts.LayoutText(value.Layout) == expected.GetProperty("layout").GetString());
            Assert.AreEqual(expected.GetProperty("preview").GetBoolean(), actual.Preview);
            Assert.AreEqual(expected.GetProperty("render").GetBoolean(), actual.Render);
            Assert.AreEqual(expected.GetProperty("export").GetBoolean(), actual.Export);
            Assert.AreEqual(expected.GetProperty("detail").GetString(), actual.Detail);
            string? issueCode = expected.GetProperty("compatibility_issue_code").GetString();
            PostProductionDocument capabilityDocument = PostProductionContracts.Empty() with
            {
                AudioLayouts = [new("fixture", actual.Layout, 2, null, [], new JsonObject())]
            };
            Assert.AreEqual(issueCode, PostProductionCapabilities.Report(capabilityDocument).Issues.SingleOrDefault()?.Code);
        }
        PostProductionDocument csvDocument = PostProductionContracts.Empty() with
        {
            AdrCues = [new("multiline", null, 0, 10, "First line\r\nSecond, line", "Actor", [], new JsonObject())]
        };
        string csvText = PostProductionInterchange.ExportAdrCsv(csvDocument).Value;
        Assert.AreEqual(csvDocument.AdrCues[0].Text, PostProductionInterchange.ImportAdrCsv(csvText).Value[0].Text);

        AdrRecordingMetadata recording = new("Actor", "U87", "Input 1", null, 48_000, 1, new JsonObject());
        PostProductionDocument reviewed = PostProductionContracts.Empty() with
        {
            AdrCues = [new("reviewed", "clip", 0, 10, "Line", "Actor",
                [new("take", "reviewed", "asset", AdrReviewStatus.Approved, true, recording, new JsonObject())], new JsonObject())]
        };
        Assert.IsFalse(PostProductionInterchange.ExportAdrCsv(reviewed).Compatibility.IsLossless);

        PostProductionDocument history = PostProductionHistory.AppendInterchange(restored, "adr_csv", "export",
            csv.Compatibility, "dialogue.csv");
        history.InterchangeHistory[0].Metadata["vendor_history"] = new JsonObject { ["kept"] = true };
        PostProductionDocument historyRoundTrip = PostProductionInterchange.ImportCanonical(
            PostProductionInterchange.ExportCanonical(history).Value).Value;
        Assert.AreEqual("adr_csv", historyRoundTrip.InterchangeHistory[0].Format);
        Assert.AreEqual("dialogue.csv", historyRoundTrip.InterchangeHistory[0].Metadata["file_name"]!.GetValue<string>());
        Assert.IsTrue(historyRoundTrip.InterchangeHistory[0].Metadata["vendor_history"]!["kept"]!.GetValue<bool>());

        TimelineEvent cmxClip = project.Tracks[0].Events[0] with
        {
            Source = new SourceRange(new SourcePosition(48_000, 48_000), new SourcePosition(48_000, 49_000))
        };
        CanonicalProject cmxProject = project with
        {
            Tracks = [project.Tracks[0] with { Events = [cmxClip] }],
            MediaAssets = [project.MediaAssets[0] with { Metadata = new JsonObject { ["reel_id"] = "REEL1" } }]
        };
        string cmx = PostProductionInterchange.ExportCmx3600(cmxProject, PostProductionContracts.Empty(), true).Value;
        StringAssert.Contains(cmx, "00:00:01:00 00:00:01:01 00:00:00:00 00:00:00:01");

        ProjectTimebase offsetTimebase = new(48_000, new FrameRate(30, 1), false, "01:00:00:00");
        CanonicalProject offsetProject = cmxProject with { Timebase = offsetTimebase };
        string offsetCmx = PostProductionInterchange.ExportCmx3600(offsetProject, PostProductionContracts.Empty(), true).Value;
        InterchangeResult<ImmutableArray<ReconformEdit>> imported = PostProductionInterchange.ImportCmx3600(offsetCmx, offsetTimebase);
        Assert.IsTrue(imported.Compatibility.IsCompatible);
        Assert.AreEqual(48_000L, imported.Value[0].OldStartSample);
        Assert.AreEqual(0L, imported.Value[0].NewStartSample);
    }

    private static CanonicalProject Project(string extra)
    {
        string comma = string.IsNullOrEmpty(extra) ? string.Empty : extra + ',';
        string defaultTimebase = extra.StartsWith("\"timebase\"", StringComparison.Ordinal) ? string.Empty : "\"timebase\":{\"sample_rate\":48000},";
        string json = "{\"id\":\"p\",\"name\":\"P\",\"revision\":1,\"schema_version\":1,\"meta\":{\"timeline\":{" + comma + defaultTimebase + "\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\",\"kind\":\"audio\"}],\"tracks\":[{\"id\":\"track\",\"type\":\"audio\",\"clips\":[{\"id\":\"clip\",\"start_sample\":\"0\",\"end_sample\":\"1000\",\"media_asset_id\":\"asset\"}]}]}}}";
        return JsonSerializer.Deserialize<ProjectDto>(json, StudioJson.Options)!.CanonicalProject;
    }
}
