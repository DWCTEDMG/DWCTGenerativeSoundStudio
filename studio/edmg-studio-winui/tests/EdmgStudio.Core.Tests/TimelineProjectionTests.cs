using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineProjectionTests
{
    [TestMethod]
    public void CrashRecovery_PrefersDirtyJournalOverNewerSnapshot()
    {
        var recovery = JsonNode.Parse(
            """
            {
              "needs_recovery": true,
              "candidates": [
                {
                  "kind": "snapshot",
                  "path": "snapshot-newest.json",
                  "saved_at": "2026-08-12T12:30:00Z"
                },
                {
                  "kind": "journal",
                  "path": "timeline-journal.json",
                  "saved_at": "2026-08-12T12:00:00Z"
                }
              ]
            }
            """)!.AsObject();

        bool selected = TimelineRecovery.TrySelectCrashRecovery(recovery, out var candidate);

        Assert.IsTrue(selected);
        Assert.AreEqual("journal", candidate.Source);
        Assert.IsNull(candidate.SnapshotName);
    }

    [TestMethod]
    public void CrashRecovery_UsesSnapshotFilenameWhenJournalIsUnavailable()
    {
        var recovery = JsonNode.Parse(
            """
            {
              "needs_recovery": true,
              "candidates": [{
                "kind": "snapshot",
                "path": "C:\\Studio\\snapshots\\snapshot-2026-08-12.json"
              }]
            }
            """)!.AsObject();

        bool selected = TimelineRecovery.TrySelectCrashRecovery(recovery, out var candidate);

        Assert.IsTrue(selected);
        Assert.AreEqual("snapshot", candidate.Source);
        Assert.AreEqual("snapshot-2026-08-12.json", candidate.SnapshotName);
    }

    [TestMethod]
    public void CrashRecovery_DoesNotRestoreCleanBackups()
    {
        var recovery = JsonNode.Parse(
            """
            {
              "needs_recovery": false,
              "candidates": [{"kind": "snapshot", "path": "snapshot.json"}]
            }
            """)!.AsObject();

        Assert.IsFalse(TimelineRecovery.TrySelectCrashRecovery(recovery, out _));
    }

    [TestMethod]
    public void TrackProjection_RebuildPreservesTimelineTrackClipAndDataMetadata()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "version": 7,
              "editor": {"snap": true},
              "tracks": [{
                "id": "track-video",
                "name": "Picture",
                "type": "video",
                "locked": true,
                "clips": [{
                  "id": "clip-1",
                  "start_s": 2.0,
                  "end_s": 8.0,
                  "source_path": "outputs/videos/source.mp4",
                  "source_in_s": 1.5,
                  "source_out_s": 7.5,
                  "speed": 1.25,
                  "volume": 0.7,
                  "muted": false,
                  "fade_in_s": 0.25,
                  "fade_out_s": 0.5,
                  "vendor": {"keep": "clip"},
                  "data": {
                    "name": "Opening",
                    "source_path": "outputs/videos/source.mp4",
                    "custom": {"keep": "data"}
                  }
                }]
              }]
            }
            """)!.AsObject();

        var lanes = TimelineProjection.Project(timeline);
        Assert.HasCount(1, lanes);
        lanes[0].Name = "Opening revised";
        lanes[0].StartSeconds = 3;
        lanes[0].EndSeconds = 9;

        var rebuilt = TimelineProjection.Rebuild(timeline, lanes);
        var track = rebuilt["tracks"]![0]!.AsObject();
        var clip = track["clips"]![0]!.AsObject();

        Assert.AreEqual(7, rebuilt["version"]!.GetValue<int>());
        Assert.IsTrue(rebuilt["editor"]!["snap"]!.GetValue<bool>());
        Assert.IsTrue(track["locked"]!.GetValue<bool>());
        Assert.AreEqual("Opening revised", clip["data"]!["name"]!.GetValue<string>());
        Assert.AreEqual("data", clip["data"]!["custom"]!["keep"]!.GetValue<string>());
        Assert.AreEqual("clip", clip["vendor"]!["keep"]!.GetValue<string>());
        Assert.AreEqual(1.5, clip["source_in_s"]!.GetValue<double>());
        Assert.AreEqual(7.5, clip["source_out_s"]!.GetValue<double>());
        Assert.AreEqual(1.25, clip["speed"]!.GetValue<double>());
        Assert.AreEqual(0.7, clip["volume"]!.GetValue<double>());
        Assert.IsFalse(clip["muted"]!.GetValue<bool>());
        Assert.AreEqual(0.25, clip["fade_in_s"]!.GetValue<double>());
        Assert.AreEqual(0.5, clip["fade_out_s"]!.GetValue<double>());
        Assert.AreEqual(3.0, clip["start_s"]!.GetValue<double>());
        Assert.AreEqual(9.0, clip["end_s"]!.GetValue<double>());
        Assert.IsTrue(TimelineProjection.HasRenderableVideoClip(rebuilt));
    }

    [TestMethod]
    public void LegacyLayers_RebuildPreservesMetadataAndSupportsDeletion()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "layers": [
                {"id":"one","name":"One","type":"video","start_s":0,"end_s":4,"custom":1},
                {"id":"two","name":"Two","type":"audio","start_s":4,"end_s":8,"custom":2}
              ]
            }
            """)!.AsObject();

        var lanes = TimelineProjection.Project(timeline);
        var rebuilt = TimelineProjection.Rebuild(timeline, lanes.Take(1));
        var layers = rebuilt["layers"]!.AsArray();

        Assert.HasCount(1, layers);
        Assert.AreEqual("one", layers[0]!["id"]!.GetValue<string>());
        Assert.AreEqual(1, layers[0]!["custom"]!.GetValue<int>());
    }

    [TestMethod]
    public void EmptyTimeline_NewLaneUsesCanonicalTrackModel()
    {
        var timeline = new JsonObject { ["revision"] = "keep" };
        var lane = TimelineProjection.CreateLane("Generated clip", "video", 1, 5);

        var rebuilt = TimelineProjection.Rebuild(timeline, [lane]);

        Assert.IsNull(rebuilt["layers"]);
        Assert.AreEqual("keep", rebuilt["revision"]!.GetValue<string>());
        var track = rebuilt["tracks"]![0]!.AsObject();
        Assert.AreEqual("video", track["type"]!.GetValue<string>());
        Assert.AreEqual("Generated clip", track["clips"]![0]!["data"]!["name"]!.GetValue<string>());
    }

    [TestMethod]
    public void InvalidLaneTimes_AreRejected()
    {
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => TimelineProjection.CreateLane("Invalid", "video", 2, 2));
    }

    [TestMethod]
    public void Move_PreservesDurationAndClampsToTimeline()
    {
        var moved = TimelineProjection.Move(GetVideoLane(), 9.5, 10);

        Assert.AreEqual(6, moved.StartSeconds);
        Assert.AreEqual(10, moved.EndSeconds);
        Assert.AreEqual(1, moved.SourceInSeconds);
        Assert.AreEqual(9, moved.SourceOutSeconds);
    }

    [TestMethod]
    public void Trim_AdjustsVideoSourceRangeUsingSpeed()
    {
        var trimmed = TimelineProjection.Trim(GetVideoLane(), 2, 4, 10);

        Assert.AreEqual(2, trimmed.StartSeconds);
        Assert.AreEqual(4, trimmed.EndSeconds);
        Assert.AreEqual(3, trimmed.SourceInSeconds);
        Assert.AreEqual(7, trimmed.SourceOutSeconds);
    }

    [TestMethod]
    public void Split_CreatesIndependentClipsAndDividesSourceRange()
    {
        var (left, right) = TimelineProjection.Split(GetVideoLane(), 3);

        Assert.AreEqual(3, left.EndSeconds);
        Assert.AreEqual(3, right.StartSeconds);
        Assert.AreEqual(5, left.SourceOutSeconds);
        Assert.AreEqual(5, right.SourceInSeconds);
        Assert.AreNotEqual(left.StableId, right.StableId);
    }

    [TestMethod]
    public void DuplicateAt_CreatesNewIdentityAtPlayhead()
    {
        var lane = GetVideoLane();
        var duplicate = TimelineProjection.DuplicateAt(lane, 8, 10);

        Assert.AreEqual(6, duplicate.StartSeconds);
        Assert.AreEqual(10, duplicate.EndSeconds);
        Assert.AreNotEqual(lane.StableId, duplicate.StableId);
    }

    [TestMethod]
    public void Rebuild_PersistsInspectorFieldsWithoutLosingUnknownMetadata()
    {
        var source = CreateVideoTimeline();
        var lane = TimelineProjection.Project(source).Single();
        lane.SourcePath = @"C:\media\replacement.mp4";
        lane.SourceInSeconds = 2.5;
        lane.SourceOutSeconds = 7.5;
        lane.Speed = 1.5;
        lane.Volume = 0.75;
        lane.Muted = true;
        lane.FadeInSeconds = 0.2;
        lane.FadeOutSeconds = 0.4;

        var rebuilt = TimelineProjection.Rebuild(source, [lane]);
        var data = rebuilt["tracks"]![0]!["clips"]![0]!["data"]!.AsObject();

        Assert.AreEqual(@"C:\media\replacement.mp4", data["source_path"]!.GetValue<string>());
        Assert.AreEqual(2.5, data["source_in_s"]!.GetValue<double>());
        Assert.AreEqual(7.5, data["source_out_s"]!.GetValue<double>());
        Assert.AreEqual(1.5, data["speed"]!.GetValue<double>());
        Assert.AreEqual(0.75, data["volume"]!.GetValue<double>());
        Assert.IsTrue(data["muted"]!.GetValue<bool>());
        Assert.AreEqual(0.2, data["fade_in_s"]!.GetValue<double>());
        Assert.AreEqual(0.4, data["fade_out_s"]!.GetValue<double>());
        Assert.AreEqual("keep-me", data["custom"]!.GetValue<string>());
        Assert.AreEqual("root-metadata", rebuilt["custom_root"]!.GetValue<string>());
    }

    [TestMethod]
    public void Rebuild_UsesTrackAssignmentAndDeterministicOrder()
    {
        var source = CreateVideoTimeline();
        var first = TimelineProjection.Project(source).Single();
        var later = TimelineProjection.ReassignTrack(
            TimelineProjection.DuplicateAt(first, 5, 12),
            1);
        var earlier = TimelineProjection.ReassignTrack(
            TimelineProjection.DuplicateAt(first, 2, 12),
            1);

        var rebuilt = TimelineProjection.Rebuild(
            source,
            TimelineProjection.OrderLanes([later, first, earlier]));

        Assert.HasCount(2, rebuilt["tracks"]!.AsArray());
        var secondTrackClips = rebuilt["tracks"]![1]!["clips"]!.AsArray();
        Assert.HasCount(2, secondTrackClips);
        Assert.AreEqual(2, secondTrackClips[0]!["start_s"]!.GetValue<double>());
        Assert.AreEqual(5, secondTrackClips[1]!["start_s"]!.GetValue<double>());
    }

    private static TimelineLaneDocument GetVideoLane() =>
        TimelineProjection.Project(CreateVideoTimeline()).Single();

    private static JsonObject CreateVideoTimeline() =>
        JsonNode.Parse(
            """
            {
              "duration_s": 12,
              "custom_root": "root-metadata",
              "tracks": [{
                "id": "video",
                "name": "Video",
                "type": "video",
                "clips": [{
                  "id": "clip-a",
                  "name": "Clip A",
                  "start_s": 1,
                  "end_s": 5,
                  "data": {
                    "source_path": "C:\\media\\source.mp4",
                    "source_in_s": 1,
                    "source_out_s": 9,
                    "speed": 2,
                    "volume": 1,
                    "muted": false,
                    "fade_in_s": 0,
                    "fade_out_s": 0,
                    "custom": "keep-me"
                  }
                }]
              }]
            }
            """)!.AsObject();
}
