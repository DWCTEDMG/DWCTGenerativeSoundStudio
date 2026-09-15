using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ProjectTimelineOperationsTests
{
    [TestMethod]
    public void AddAndReorderTrack_ReturnImmutableProjectAndBackendCompatibleOperations()
    {
        CanonicalProject original = CreateProject();

        ProjectTimelineMutation added = ProjectTimelineOperations.AddTrack(original, "audio", "audio", "Dialogue");
        ProjectTimelineMutation reordered = ProjectTimelineOperations.ReorderTrack(added.Project, "audio", 0);

        Assert.HasCount(1, original.Tracks);
        Assert.AreEqual("audio", added.Project.Tracks[1].Id);
        Assert.AreEqual("audio", added.Operation["track_type"]!.GetValue<string>());
        Assert.AreEqual("audio", reordered.Project.Tracks[0].Id);
        Assert.AreEqual(0, reordered.Project.Tracks[0].Order);
        Assert.AreEqual(1, reordered.Project.Tracks[1].Order);
        Assert.AreEqual(0, reordered.Operation["index"]!.GetValue<int>());
    }

    [TestMethod]
    public void SetTrackState_PreservesRoutingMetadataAndEmitsOnlyRequestedValues()
    {
        CanonicalProject original = CreateProject();

        ProjectTimelineMutation mutation = ProjectTimelineOperations.SetTrackState(
            original,
            "video",
            muted: true,
            solo: false,
            recordArmed: true,
            inputMonitoring: true);

        Track track = mutation.Project.Tracks.Single();
        Assert.IsTrue(track.Muted);
        Assert.IsFalse(track.Solo);
        Assert.IsTrue(track.RecordArmed);
        Assert.IsTrue(track.InputMonitoring);
        Assert.AreEqual("main", track.Metadata["routing"]!["bus"]!.GetValue<string>());
        Assert.IsNull(mutation.Operation["locked"]);
        Assert.IsTrue(mutation.Operation["muted"]!.GetValue<bool>());
        Assert.IsFalse(mutation.Operation["solo"]!.GetValue<bool>());

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(mutation.Project);
        Assert.AreEqual("main", rebuilt["tracks"]![0]!["routing"]!["bus"]!.GetValue<string>());
        Assert.IsTrue(rebuilt["tracks"]![0]!["record_armed"]!.GetValue<bool>());
    }

    [TestMethod]
    public void Operations_RejectDuplicateIdsAndInvalidRequests()
    {
        CanonicalProject project = CreateProject();

        Assert.Throws<InvalidOperationException>(() => ProjectTimelineOperations.AddTrack(project, "video", "audio"));
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.AddTrack(project, "new", "unsupported"));
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.ReorderTrack(project, "video", 1));
        Assert.Throws<ArgumentException>(() => ProjectTimelineOperations.SetTrackState(project, "video"));
    }

    [TestMethod]
    public void LockedTrack_AllowsOnlyUnlockBeforeOtherStateChanges()
    {
        CanonicalProject project = CreateProject();
        CanonicalProject locked = ProjectTimelineOperations.SetTrackState(project, "video", locked: true).Project;

        Assert.Throws<InvalidOperationException>(() => ProjectTimelineOperations.ReorderTrack(locked, "video", 0));
        Assert.Throws<InvalidOperationException>(() => ProjectTimelineOperations.SetTrackState(locked, "video", muted: true));
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.SetTrackState(locked, "video", locked: false, muted: true));

        CanonicalProject unlocked = ProjectTimelineOperations.SetTrackState(locked, "video", locked: false).Project;
        Assert.IsFalse(unlocked.Tracks.Single().Locked);
    }

    [TestMethod]
    public void EventOperations_PreserveExactSamplesAndSourcePhase()
    {
        CanonicalProject project = CreateProject(
            "\"start_sample\":\"9007199254740993\",\"end_sample\":\"9007199254788993\"," +
            "\"data\":{\"name\":\"Shot\",\"source_sample_rate\":44100,\"source_offset_sample\":\"10\",\"source_offset_remainder\":\"1/3\",\"speed\":2,\"active_take_id\":\"take-b\"}",
            "\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\"}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"take-a\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"},{\"id\":\"take-b\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"}],\"comp_ranges\":[{\"id\":\"left\",\"clip_id\":\"clip\",\"take_id\":\"take-a\",\"start_sample\":\"9007199254740993\",\"end_sample\":\"9007199254748993\"},{\"id\":\"cross\",\"clip_id\":\"clip\",\"take_id\":\"take-b\",\"start_sample\":\"9007199254748993\",\"end_sample\":\"9007199254788993\"}],\"crossfades\":[]},");
        long splitSample = 9007199254748993;

        ProjectTimelineMutation split = ProjectTimelineOperations.SplitEvent(
            project, "video", "clip", new TimelinePosition(splitSample), "right",
            ["right-take-a", "right-take-b"], ["right-comp"]);

        TimelineEvent left = split.Project.Tracks.Single().Events[0];
        TimelineEvent right = split.Project.Tracks.Single().Events[1];
        Assert.AreEqual(splitSample, left.End.Samples);
        Assert.AreEqual(splitSample, right.Start.Samples);
        Assert.AreEqual(14710, right.Source!.Start.Samples);
        Assert.AreEqual("1/3", right.Source.Start.Remainder);
        Assert.AreEqual("9007199254748993", split.Operation["position"]!.GetValue<string>());
        Assert.AreEqual("right", split.Operation["new_id"]!.GetValue<string>());
        CollectionAssert.AreEqual(new[] { "right-take-a", "right-take-b" },
            split.Operation["right_take_ids"]!.AsArray().Select(item => item!.GetValue<string>()).ToArray());
        CollectionAssert.AreEqual(new[] { "right-comp" },
            split.Operation["right_comp_ids"]!.AsArray().Select(item => item!.GetValue<string>()).ToArray());
        ProfessionalEditingDocument splitEditing = ProfessionalEditingContracts.Read(split.Project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(split.Project, splitEditing);
        Assert.AreEqual("right-take-b", right.Data["data"]!["active_take_id"]!.GetValue<string>());
        CollectionAssert.AreEqual(
            new[] { ("left", "clip", "take-a", 9007199254740993L, splitSample),
                    ("right-comp", "right", "right-take-b", splitSample, 9007199254788993L) },
            splitEditing.CompRanges.Select(comp => (comp.Id, comp.ClipId, comp.TakeId, comp.StartSample, comp.EndSample)).ToArray());

        ProjectTimelineMutation trimmed = ProjectTimelineOperations.TrimEvent(
            split.Project, "video", "right", "start", new TimelinePosition(splitSample + 1));
        Assert.AreEqual(14712, trimmed.Project.Tracks.Single().Events[1].Source!.Start.Samples);
        Assert.AreEqual("41/240", trimmed.Project.Tracks.Single().Events[1].Source!.Start.Remainder);
        Assert.AreEqual(10, project.Tracks.Single().Events.Single().Source!.Start.Samples);
    }

    [TestMethod]
    public void EventOperations_RejectLockedInvalidAndDuplicateChanges()
    {
        CanonicalProject project = CreateProject();
        CanonicalProject locked = ProjectTimelineOperations.SetTrackState(project, "video", locked: true).Project;

        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.MoveEvent(locked, "video", "clip", new TimelinePosition(1)));
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            ProjectTimelineOperations.TrimEvent(project, "video", "clip", "start", new TimelinePosition(48_000)));
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.SplitEvent(project, "video", "clip", new TimelinePosition(24_000), "video"));
    }

    [TestMethod]
    public void DuplicateEvent_EmitsDeterministicTakeAndCompIds()
    {
        CanonicalProject project = CreateProject(
            "\"start_sample\":\"0\",\"end_sample\":\"48000\",\"data\":{\"active_take_id\":\"take\"}",
            "\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\"}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"take\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"}],\"comp_ranges\":[{\"id\":\"comp\",\"clip_id\":\"clip\",\"take_id\":\"take\",\"start_sample\":\"0\",\"end_sample\":\"100\"}]},");

        ProjectTimelineMutation duplicate = ProjectTimelineOperations.DuplicateEvent(
            project, "video", "clip", "copy", ["copy-take"], ["copy-comp"]);

        CollectionAssert.AreEqual(new[] { "copy-take" }, duplicate.Operation["new_take_ids"]!.AsArray().Select(node => node!.GetValue<string>()).ToArray());
        CollectionAssert.AreEqual(new[] { "copy-comp" }, duplicate.Operation["new_comp_ids"]!.AsArray().Select(node => node!.GetValue<string>()).ToArray());
        ProfessionalEditingDocument editing = ProfessionalEditingContracts.Read(duplicate.Project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(duplicate.Project, editing);
        TimelineEvent copy = duplicate.Project.Tracks.Single().Events.Single(item => item.Id == "copy");
        Assert.AreEqual("copy-take", copy.Data["data"]!["active_take_id"]!.GetValue<string>());
        Assert.IsTrue(editing.Takes.Any(take => take.Id == "copy-take" && take.ClipId == "copy"));
        Assert.IsTrue(editing.CompRanges.Any(comp => comp.Id == "copy-comp" && comp.ClipId == "copy" &&
            comp.TakeId == "copy-take" && comp.StartSample == 48_000 && comp.EndSample == 48_100));
    }

    [TestMethod]
    public void MoveTrimAndDelete_ReturnValidatedProjectsWithBackendEquivalentEditing()
    {
        CanonicalProject movedProject = CreateEditingProject();
        ProjectTimelineMutation moved = ProjectTimelineOperations.MoveEvent(
            movedProject, "video", "clip", new TimelinePosition(90));
        ProfessionalEditingDocument movedEditing = ProfessionalEditingContracts.Read(moved.Project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(moved.Project, movedEditing);
        CompRange movedComp = movedEditing.CompRanges.Single();
        Assert.AreEqual((90L, 180L), (movedComp.StartSample, movedComp.EndSample));
        CollectionAssert.AreEqual(new[] { ("left-xf", 90L, 100L), ("right-xf", 160L, 180L) },
            movedEditing.Crossfades.Select(item => (item.Id, item.StartSample, item.EndSample)).ToArray());

        ProjectTimelineMutation trimmed = ProjectTimelineOperations.TrimEvent(
            CreateEditingProject(), "video", "clip", "start", new TimelinePosition(90));
        ProfessionalEditingDocument trimmedEditing = ProfessionalEditingContracts.Read(trimmed.Project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(trimmed.Project, trimmedEditing);
        CompRange trimmedComp = trimmedEditing.CompRanges.Single();
        Assert.AreEqual((90L, 170L), (trimmedComp.StartSample, trimmedComp.EndSample));
        CollectionAssert.AreEqual(new[] { ("left-xf", 90L, 100L), ("right-xf", 160L, 180L) },
            trimmedEditing.Crossfades.Select(item => (item.Id, item.StartSample, item.EndSample)).ToArray());

        ProjectTimelineMutation deleted = ProjectTimelineOperations.DeleteEvent(CreateEditingProject(), "video", "clip");
        ProfessionalEditingDocument deletedEditing = ProfessionalEditingContracts.Read(deleted.Project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(deleted.Project, deletedEditing);
        Assert.IsEmpty(deletedEditing.Takes);
        Assert.IsEmpty(deletedEditing.CompRanges);
        Assert.IsEmpty(deletedEditing.Crossfades);
        Assert.IsFalse(deleted.Project.Timeline["tracks"]![0]!["clips"]!.AsArray()
            .Any(node => node!["id"]!.GetValue<string>() == "clip"));
    }

    [TestMethod]
    public void Split_ReconcilesCrossfadesWithoutChangingEndpointOwnership()
    {
        ProjectTimelineMutation split = ProjectTimelineOperations.SplitEvent(
            CreateEditingProject(), "video", "clip", new TimelinePosition(90), "split-right",
            ["split-take"], ["split-comp"]);

        ProfessionalEditingDocument editing = ProfessionalEditingContracts.Read(split.Project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(split.Project, editing);
        Crossfade crossfade = editing.Crossfades.Single();
        Assert.AreEqual("left-xf", crossfade.Id);
        Assert.AreEqual("previous", crossfade.LeftClipId);
        Assert.AreEqual("clip", crossfade.RightClipId);
        Assert.AreEqual(80, crossfade.StartSample);
        Assert.AreEqual(90, crossfade.EndSample);
        Assert.IsFalse(editing.Crossfades.Any(item => item.LeftClipId == "split-right" || item.RightClipId == "split-right"));
    }

    [TestMethod]
    public void Markers_RoundTripAndEmitBackendCompatibleOperations()
    {
        CanonicalProject project = CreateProject();
        ProjectTimelineMutation added = ProjectTimelineOperations.AddMarker(
            project, "chorus", "Chorus", new TimelinePosition(96_000), "#FF00FF");
        ProjectTimelineMutation moved = ProjectTimelineOperations.MoveMarker(
            added.Project, "chorus", new TimelinePosition(72_000));

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(moved.Project);
        Assert.AreEqual("72000", rebuilt["markers"]![0]!["position_sample"]!.GetValue<string>());
        Assert.AreEqual("move_marker", moved.Operation["kind"]!.GetValue<string>());
        Assert.AreEqual("72000", moved.Operation["position"]!.GetValue<string>());
        Assert.IsEmpty(ProjectTimelineOperations.DeleteMarker(moved.Project, "chorus").Project.Markers);
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.AddMarker(project, "clip", "Duplicate", new TimelinePosition(0)));
        CanonicalProject withMarker = ProjectTimelineOperations.AddMarker(
            project, "marker-id", "Marker", new TimelinePosition(0)).Project;
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.AddTrack(withMarker, "marker-id", "video"));
    }

    [TestMethod]
    public void Snap_UsesExactFrameAndFractionalBeatGrids()
    {
        var timebase = new ProjectTimebase(48_000, new FrameRate(30_000, 1_001));

        Assert.AreEqual(1602, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(1601), TimelineSnapMode.Frame).Samples);
        Assert.AreEqual(24_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(23_999), TimelineSnapMode.Beat, 120).Samples);
        Assert.AreEqual(16_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(15_999), TimelineSnapMode.HalfBeat, 90).Samples);
        Assert.AreEqual(6_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(6_000), TimelineSnapMode.QuarterBeat, 120).Samples);
        Assert.AreEqual(23_976, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(24_000), TimelineSnapMode.Beat, 120.12m).Samples);
        Assert.AreEqual(24_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(12_000), TimelineSnapMode.Beat, 120).Samples);
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(1), TimelineSnapMode.Beat, 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(1), TimelineSnapMode.Beat, -1));
    }

    private static CanonicalProject CreateProject(
        string clipJson = "\"start_sample\":\"0\",\"end_sample\":\"48000\"",
        string timelinePrefix = "")
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            "{\"id\":\"project\",\"name\":\"Project\",\"revision\":3,\"schema_version\":1,\"meta\":{\"timeline\":{" + timelinePrefix +
            "\"timebase\":{\"sample_rate\":48000,\"frame_rate\":{\"numerator\":30,\"denominator\":1}}," +
            "\"tracks\":[{\"id\":\"video\",\"name\":\"Picture\",\"type\":\"video\",\"routing\":{\"bus\":\"main\"}," +
            "\"clips\":[{\"id\":\"clip\"," + clipJson + "}]}]}}}",
            StudioJson.Options)!;
        return dto.CanonicalProject;
    }

    private static CanonicalProject CreateEditingProject()
    {
        const string json = "{\"id\":\"project\",\"name\":\"Project\",\"revision\":3,\"schema_version\":1,\"meta\":{\"timeline\":{\"timebase\":{\"sample_rate\":48000},\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\"}],\"tracks\":[{\"id\":\"video\",\"type\":\"video\",\"clips\":[{\"id\":\"previous\",\"start_sample\":\"0\",\"end_sample\":\"100\"},{\"id\":\"clip\",\"start_sample\":\"80\",\"end_sample\":\"180\",\"data\":{\"active_take_id\":\"take\"}},{\"id\":\"next\",\"start_sample\":\"160\",\"end_sample\":\"260\"}]}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"take\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"}],\"comp_ranges\":[{\"id\":\"comp\",\"clip_id\":\"clip\",\"take_id\":\"take\",\"start_sample\":\"80\",\"end_sample\":\"170\"}],\"crossfades\":[{\"id\":\"left-xf\",\"track_id\":\"video\",\"left_clip_id\":\"previous\",\"right_clip_id\":\"clip\",\"start_sample\":\"80\",\"end_sample\":\"100\"},{\"id\":\"right-xf\",\"track_id\":\"video\",\"left_clip_id\":\"clip\",\"right_clip_id\":\"next\",\"start_sample\":\"160\",\"end_sample\":\"180\"}]}}}}";
        return JsonSerializer.Deserialize<ProjectDto>(json, StudioJson.Options)!.CanonicalProject;
    }
}
