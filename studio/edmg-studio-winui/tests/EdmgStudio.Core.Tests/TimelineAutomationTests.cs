using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineAutomationTests
{
    [TestMethod]
    public void AssignSource_UpdatesSelectedClipAndPreservesUnknownMetadata()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "revision": "keep-root",
              "tracks": [{
                "id": "picture",
                "type": "video",
                "locked": false,
                "clips": [{
                  "id": "clip-1",
                  "start_s": 1,
                  "end_s": 5,
                  "vendor": {"keep": "clip"},
                  "data": {
                    "name": "Opening",
                    "custom": {"keep": "data"}
                  }
                }]
              }]
            }
            """)!.AsObject();

        TimelineAutomationResult result = TimelineAutomation.AssignSource(
            timeline,
            "clip-1",
            "  outputs/videos/opening.mp4  ");

        Assert.AreEqual("assign_source", result.Operation);
        Assert.AreEqual(1, result.ChangedClipCount);
        var track = result.Timeline["tracks"]![0]!.AsObject();
        var clip = track["clips"]![0]!.AsObject();
        Assert.AreEqual("keep-root", result.Timeline["revision"]!.GetValue<string>());
        Assert.IsFalse(track["locked"]!.GetValue<bool>());
        Assert.AreEqual("clip", clip["vendor"]!["keep"]!.GetValue<string>());
        Assert.AreEqual("data", clip["data"]!["custom"]!["keep"]!.GetValue<string>());
        Assert.AreEqual(
            "outputs/videos/opening.mp4",
            clip["data"]!["source_path"]!.GetValue<string>());
    }

    [TestMethod]
    public void AddSourceClip_InfersAudioAndVideoAndPreservesRootMetadata()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "editor": {"snap": true},
              "tracks": []
            }
            """)!.AsObject();

        TimelineAutomationResult audio = TimelineAutomation.AddSourceClip(
            timeline,
            "assets/audio/score.WAV",
            2,
            6,
            0);
        TimelineAutomationResult video = TimelineAutomation.AddSourceClip(
            audio.Timeline,
            "assets/refs/opening.mov",
            9,
            3,
            1);

        Assert.AreEqual("add_source_clip", audio.Operation);
        Assert.AreEqual(1, audio.ChangedClipCount);
        Assert.IsTrue(video.Timeline["editor"]!["snap"]!.GetValue<bool>());
        var lanes = TimelineProjection.Project(video.Timeline);
        Assert.HasCount(2, lanes);
        Assert.AreEqual("audio", lanes.Single(lane => lane.TrackIndex == 0).Type);
        Assert.AreEqual("assets/audio/score.WAV", lanes.Single(lane => lane.TrackIndex == 0).SourcePath);
        Assert.AreEqual(6D, lanes.Single(lane => lane.TrackIndex == 0).SourceOutSeconds);
        Assert.AreEqual("video", lanes.Single(lane => lane.TrackIndex == 1).Type);
        Assert.AreEqual("assets/refs/opening.mov", lanes.Single(lane => lane.TrackIndex == 1).SourcePath);
    }

    [TestMethod]
    public void SequenceTrack_UsesTimelineOrderAndPreservesDurationsAndMetadata()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "tracks": [{
                "id": "picture",
                "type": "video",
                "clips": [
                  {
                    "id": "late",
                    "start_s": 10,
                    "end_s": 12,
                    "data": {"name": "Late"},
                    "vendor": "keep-late"
                  },
                  {
                    "id": "early",
                    "start_s": 1,
                    "end_s": 4,
                    "data": {"name": "Early"},
                    "vendor": "keep-early"
                  }
                ]
              }]
            }
            """)!.AsObject();

        TimelineAutomationResult result = TimelineAutomation.SequenceTrack(timeline, 0, 5, 0.5);

        Assert.AreEqual("sequence_track", result.Operation);
        Assert.AreEqual(2, result.ChangedClipCount);
        var lanes = TimelineProjection.Project(result.Timeline);
        TimelineLaneDocument early = lanes.Single(lane => lane.StableId == "early");
        TimelineLaneDocument late = lanes.Single(lane => lane.StableId == "late");
        Assert.AreEqual(5D, early.StartSeconds);
        Assert.AreEqual(8D, early.EndSeconds);
        Assert.AreEqual(8.5D, late.StartSeconds);
        Assert.AreEqual(10.5D, late.EndSeconds);

        var clips = result.Timeline["tracks"]![0]!["clips"]!.AsArray();
        Assert.AreEqual(
            "keep-early",
            clips.Single(clip => clip!["id"]!.GetValue<string>() == "early")!["vendor"]!.GetValue<string>());
        Assert.AreEqual(
            "keep-late",
            clips.Single(clip => clip!["id"]!.GetValue<string>() == "late")!["vendor"]!.GetValue<string>());
    }

    [TestMethod]
    public void AutomationOperations_RejectInvalidOrStaleInput()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "tracks": [{
                "id": "picture",
                "type": "video",
                "clips": [{
                  "id": "clip-1",
                  "start_s": 0,
                  "end_s": 4,
                  "data": {"name": "Opening"}
                }]
              }]
            }
            """)!.AsObject();

        Assert.ThrowsExactly<InvalidOperationException>(() =>
            TimelineAutomation.AssignSource(timeline, "missing", "source.mp4"));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
            TimelineAutomation.AddSourceClip(timeline, "source.mp4", -1, 2, 0));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
            TimelineAutomation.AddSourceClip(timeline, "source.mp4", 0, 0, 0));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
            TimelineAutomation.SequenceTrack(timeline, 0, 0, -0.1));
        Assert.ThrowsExactly<InvalidOperationException>(() =>
            TimelineAutomation.SequenceTrack(timeline, 1, 0, 0));
    }

    [TestMethod]
    public void AutomationOperations_RejectLockedTracks()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "tracks": [{
                "id": "picture",
                "type": "video",
                "locked": true,
                "clips": [{
                  "id": "clip-1",
                  "start_s": 0,
                  "end_s": 4,
                  "data": {"name": "Opening"}
                }]
              }]
            }
            """)!.AsObject();

        Assert.ThrowsExactly<InvalidOperationException>(() =>
            TimelineAutomation.AssignSource(timeline, "clip-1", "source.mp4"));
        Assert.ThrowsExactly<InvalidOperationException>(() =>
            TimelineAutomation.AddSourceClip(timeline, "source.mp4", 0, 2, 0));
        Assert.ThrowsExactly<InvalidOperationException>(() =>
            TimelineAutomation.SequenceTrack(timeline, 0, 0, 0));
    }
}
