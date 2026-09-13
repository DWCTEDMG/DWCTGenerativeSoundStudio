using System.Collections.Immutable;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class AudioEngineContractsTests
{
    [TestMethod]
    public void RenderGraphAppliesMuteAndSoloBeforeCallbackConsumption()
    {
        var graph = new AudioRenderGraph(new AudioEngineConfiguration(
            "project", "device", 48_000, 256,
            [
                new AudioTrackRoute("music", "master", 1, 0, false, false, []),
                new AudioTrackRoute("dialog", "master", 1, 0, false, true, []),
                new AudioTrackRoute("muted", "master", 1, 0, true, true, [])
            ]));

        Assert.IsFalse(graph.TryGetAudibleRoute("music", out _));
        Assert.IsTrue(graph.TryGetAudibleRoute("dialog", out AudioTrackRoute? dialog));
        Assert.AreEqual("master", dialog!.OutputBusId);
        Assert.IsFalse(graph.TryGetAudibleRoute("muted", out _));
    }

    [TestMethod]
    public void CommandQueueIsBoundedAndPreservesOrder()
    {
        var queue = new AudioEngineCommandQueue(2);
        TransportState state = new("project", 48_000, 96_000, 0, TransportMode.Playing,
            new TransportLoop(false, 0, 96_000));

        Assert.IsTrue(queue.TryEnqueue(new AudioEngineCommand(AudioEngineCommandKind.Transport, null, state)));
        Assert.IsTrue(queue.TryEnqueue(new AudioEngineCommand(AudioEngineCommandKind.Shutdown, null, null)));
        Assert.IsFalse(queue.TryEnqueue(new AudioEngineCommand(AudioEngineCommandKind.Shutdown, null, null)));
        Assert.IsTrue(queue.TryDequeue(out AudioEngineCommand first));
        Assert.AreEqual(AudioEngineCommandKind.Transport, first.Kind);
        Assert.IsTrue(queue.TryDequeue(out AudioEngineCommand second));
        Assert.AreEqual(AudioEngineCommandKind.Shutdown, second.Kind);
        Assert.IsFalse(queue.TryDequeue(out _));
    }

    [TestMethod]
    public void GraphBuilderResolvesCanonicalAudioClipsAndRouting()
    {
        var asset = new MediaAsset("asset", "assets/media/source.wav", "audio", []);
        var timelineEvent = new TimelineEvent(
            "clip", "Clip", "audio", new TimelinePosition(100), new TimelinePosition(400), "asset", [],
            new SourceRange(new SourcePosition(44_100, 25), null));
        var track = new Track(
            "track", "Audio", "audio", 0, false, false, false, false, false, [timelineEvent],
            new JsonObject
            {
                ["gain"] = 0.75f,
                ["pan"] = -0.25f,
                ["routing"] = new JsonObject { ["bus"] = "dialog" }
            });
        var project = new CanonicalProject(
            "project", "Project", 1, 1, new ProjectTimebase(), [track], [asset], [], [], []);

        AudioRenderGraph graph = AudioRenderGraphBuilder.Build(project, "device", 128, item => $"C:\\project\\{item.Path}");

        Assert.IsTrue(graph.TryGetAudibleRoute("track", out AudioTrackRoute? route));
        Assert.AreEqual("dialog", route!.OutputBusId);
        Assert.AreEqual(0.75f, route.Gain);
        Assert.AreEqual(-0.25f, route.Pan);
        AudioClipSource clip = route.Clips.Single();
        Assert.AreEqual(100, clip.TimelineStartSample);
        Assert.AreEqual(25, clip.SourceStartSample);
        Assert.AreEqual(44_100, clip.SourceSampleRate);
    }
}
