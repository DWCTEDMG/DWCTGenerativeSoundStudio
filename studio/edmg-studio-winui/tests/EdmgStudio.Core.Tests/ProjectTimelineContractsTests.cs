using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ProjectTimelineContractsTests
{
    [TestMethod]
    public void FromProject_UsesExactSamplesAndPreservesUnknownTimelineMetadata()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """
            {
              "id": "project-1", "name": "Canonical project", "revision": 42, "schema_version": 7,
              "meta": {
                "director_document": {"keep": true},
                "media_pool": [{"id":"asset-1","path":"audio/song.wav","kind":"audio","hash":"abc"}],
                "timeline": {
                  "vendor": {"keep": "timeline"},
                  "timebase": {"sample_rate":48000,"frame_rate":{"numerator":30000,"denominator":1001}},
                  "tracks": [{"id":"picture","name":"Picture","type":"video","locked":true,
                    "muted":true,"solo":false,"record_armed":true,"input_monitoring":true,
                    "vendor":{"keep":"track"},"clips":[{"id":"scene-1","start_sample":"48000",
                    "end_sample":"144000","start_s":999,"end_s":1000,"media_asset_id":"asset-1",
                    "camera":{"yaw":3},"data":{"name":"Opening","reviewed_motion":true}}]}]
                }
              }
            }
            """,
            StudioJson.Options)!;

        CanonicalProject project = dto.CanonicalProject;

        Assert.AreEqual(48_000, project.Timebase.SampleRate);
        Assert.AreEqual(new FrameRate(30_000, 1_001), project.Timebase.FrameRate);
        Assert.AreEqual(48_000L, project.Tracks.Single().Events.Single().Start.Samples);
        Assert.AreEqual(144_000L, project.Tracks.Single().Events.Single().End.Samples);
        Assert.AreEqual("asset-1", project.Tracks.Single().Events.Single().MediaAssetId);
        Assert.AreEqual("abc", project.MediaAssets.Single().Metadata["hash"]!.GetValue<string>());
        Assert.AreEqual(0, project.Tracks.Single().Order);
        Assert.IsTrue(project.Tracks.Single().Muted);
        Assert.IsFalse(project.Tracks.Single().Solo);
        Assert.IsTrue(project.Tracks.Single().RecordArmed);
        Assert.IsTrue(project.Tracks.Single().InputMonitoring);

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(project);
        Assert.AreEqual("timeline", rebuilt["vendor"]!["keep"]!.GetValue<string>());
        Assert.AreEqual("track", rebuilt["tracks"]![0]!["vendor"]!["keep"]!.GetValue<string>());
        Assert.AreEqual(3, rebuilt["tracks"]![0]!["clips"]![0]!["camera"]!["yaw"]!.GetValue<int>());
        Assert.IsTrue(rebuilt["tracks"]![0]!["clips"]![0]!["data"]!["reviewed_motion"]!.GetValue<bool>());
        Assert.AreEqual(1d, rebuilt["tracks"]![0]!["clips"]![0]!["start_s"]!.GetValue<double>());
        Assert.AreEqual("48000", rebuilt["tracks"]![0]!["clips"]![0]!["start_sample"]!.GetValue<string>());
        Assert.IsTrue(rebuilt["tracks"]![0]!["muted"]!.GetValue<bool>());
        Assert.IsFalse(rebuilt["tracks"]![0]!["solo"]!.GetValue<bool>());
    }

    [TestMethod]
    public void ProjectTimebase_RoundTripsProfessionalFrameAndSamplePositions()
    {
        var timebase = new ProjectTimebase(48_000, new FrameRate(30_000, 1_001));
        TimelinePosition framePosition = timebase.FromFrame(1_001);

        Assert.AreEqual(1_603_202L, framePosition.Samples);
        Assert.AreEqual(1_001L, timebase.ToFrame(framePosition));
        Assert.AreEqual(new TimelinePosition(24_000), timebase.FromSeconds(0.5));
        Assert.AreEqual(0.5d, timebase.ToSeconds(new TimelinePosition(24_000)));
    }

    [TestMethod]
    public void FromProject_RejectsAnEventThatEndsBeforeItStarts()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"invalid","name":"Invalid","revision":1,"schema_version":1,"meta":{"timeline":{"tracks":[{"clips":[{"id":"bad","start_sample":"2","end_sample":"1"}]}]}}}""",
            StudioJson.Options)!;

        Assert.Throws<InvalidDataException>(() => ProjectTimelineContracts.FromProject(dto));
    }

    [TestMethod]
    public void FromProject_AcceptsIntegerSamplesAndRejectsMalformedExplicitSamples()
    {
        ProjectDto integerDto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"integer","name":"Integer","meta":{"timeline":{"tracks":[{"clips":[{"start_sample":2,"end_sample":3}]}]}}}""",
            StudioJson.Options)!;
        ProjectDto malformedDto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"bad","name":"Bad","meta":{"timeline":{"tracks":[{"clips":[{"start_sample":"02","end_sample":"3"}]}]}}}""",
            StudioJson.Options)!;

        Assert.AreEqual(2L, integerDto.CanonicalProject.Tracks.Single().Events.Single().Start.Samples);
        Assert.Throws<InvalidDataException>(() => malformedDto.CanonicalProject);
    }

    [TestMethod]
    public void FromProject_RejectsNegativePositionsAndDuplicateTimelineIds()
    {
        ProjectDto negativeDto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"negative","name":"Negative","meta":{"timeline":{"tracks":[{"id":"video","clips":[{"id":"clip","start_sample":"-1","end_sample":"3"}]}]}}}""",
            StudioJson.Options)!;
        ProjectDto duplicateDto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"duplicate","name":"Duplicate","meta":{"timeline":{"tracks":[{"id":"same","clips":[{"id":"same","start_sample":"0","end_sample":"3"}]}]}}}""",
            StudioJson.Options)!;

        Assert.Throws<InvalidDataException>(() => negativeDto.CanonicalProject);
        Assert.Throws<InvalidDataException>(() => duplicateDto.CanonicalProject);
    }

    [TestMethod]
    public void FromProject_ReadsLegacyMarkerTime()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"legacy-marker","name":"Legacy marker","meta":{"timeline":{"tracks":[],"markers":[{"id":"cue","t":1.25,"label":"Cue"}]}}}""",
            StudioJson.Options)!;

        TimelineMarker marker = dto.CanonicalProject.Markers.Single();

        Assert.AreEqual("Cue", marker.Name);
        Assert.AreEqual(60_000L, marker.Position.Samples);
    }

    [TestMethod]
    public void FromProject_PreservesExactMarkersAndRejectsCrossDomainIdCollisions()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"markers","name":"Markers","meta":{"timeline":{"tracks":[{"id":"video","clips":[{"id":"clip","start_sample":"0","end_sample":"3"}]}],"markers":[{"id":"chapter","label":"Chapter","position_sample":"9007199254740993","vendor":{"keep":true}}]}}}""",
            StudioJson.Options)!;
        ProjectDto collisionDto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"collision","name":"Collision","meta":{"timeline":{"tracks":[{"id":"video","clips":[]}],"markers":[{"id":"video","position_sample":"0"}]}}}""",
            StudioJson.Options)!;

        CanonicalProject project = dto.CanonicalProject;
        Assert.AreEqual("Chapter", project.Markers.Single().Name);
        Assert.AreEqual(9_007_199_254_740_993L, project.Markers.Single().Position.Samples);
        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(project);
        Assert.AreEqual("9007199254740993", rebuilt["markers"]![0]!["position_sample"]!.GetValue<string>());
        Assert.IsTrue(rebuilt["markers"]![0]!["vendor"]!["keep"]!.GetValue<bool>());
        Assert.Throws<InvalidDataException>(() => collisionDto.CanonicalProject);
    }

    [TestMethod]
    public void RebuildTimeline_UsesCanonicalEventTypeAndClearsMediaReferences()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"event","name":"Event","meta":{"timeline":{"tracks":[{"id":"video","clips":[{"id":"clip","type":"video","media_asset_id":"old","start_sample":"0","end_sample":"3","data":{"media_asset_id":"old"}}]}]}}}""",
            StudioJson.Options)!;
        CanonicalProject project = dto.CanonicalProject;
        TimelineEvent changed = project.Tracks[0].Events[0] with { Type = "audio", MediaAssetId = null };
        project = project with { Tracks = [project.Tracks[0] with { Events = [changed] }] };

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(project);

        Assert.AreEqual("audio", rebuilt["tracks"]![0]!["clips"]![0]!["type"]!.GetValue<string>());
        Assert.IsNull(rebuilt["tracks"]![0]!["clips"]![0]!["media_asset_id"]);
        Assert.IsNull(rebuilt["tracks"]![0]!["clips"]![0]!["data"]!["media_asset_id"]);
    }

    [TestMethod]
    public void InsertRenderResult_UsesExactPlayheadAndPreservesReviewedMetadata()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"insert","name":"Insert","meta":{"timeline":{"vendor":{"keep":true},"timebase":{"sample_rate":48000,"frame_rate":{"numerator":30,"denominator":1}},"tracks":[{"id":"locked","type":"video","locked":true,"clips":[]},{"id":"video","type":"video","vendor":{"track":true},"clips":[{"id":"reviewed","start_sample":"0","end_sample":"48000","camera":{"yaw":2},"data":{"reviewed_motion":true}}]}]}}}""",
            StudioJson.Options)!;
        CanonicalProject project = dto.CanonicalProject;

        CanonicalTimelineInsertionResult inserted = RenderResultTimelineInsertion.Insert(
            project,
            new RenderResultDescriptor("job-1", "outputs/final.mp4", 2, new JsonObject { ["vendor"] = "asset" }),
            new TimelinePosition(90_071_992_547_409_993));
        CanonicalTimelineInsertionResult replay = RenderResultTimelineInsertion.Insert(
            inserted.Project,
            new RenderResultDescriptor("job-1", "outputs/final.mp4"),
            new TimelinePosition(0));
        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(inserted.Project);

        Assert.AreEqual("video", inserted.TrackId);
        Assert.AreEqual(90_071_992_547_409_993L, inserted.Project.Tracks[1].Events.Last().Start.Samples);
        Assert.AreEqual("asset", inserted.Project.MediaAssets.Last().Metadata["vendor"]!.GetValue<string>());
        Assert.IsTrue(replay.Replayed);
        Assert.AreEqual(inserted.Project.Tracks.Sum(track => track.Events.Count), replay.Project.Tracks.Sum(track => track.Events.Count));
        Assert.IsTrue(rebuilt["vendor"]!["keep"]!.GetValue<bool>());
        Assert.AreEqual(2, rebuilt["tracks"]![1]!["clips"]![0]!["camera"]!["yaw"]!.GetValue<int>());
        Assert.IsTrue(rebuilt["tracks"]![1]!["clips"]![0]!["data"]!["reviewed_motion"]!.GetValue<bool>());
    }

    [TestMethod]
    public void InsertRenderResult_CreatesUnlockedVideoTrackWhenNoneIsAvailable()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"insert-new","name":"Insert","meta":{"timeline":{"tracks":[{"id":"audio","type":"audio","clips":[]},{"id":"locked","type":"video","locked":true,"clips":[]}]}}}""",
            StudioJson.Options)!;

        CanonicalTimelineInsertionResult inserted = RenderResultTimelineInsertion.Insert(
            dto.CanonicalProject,
            new RenderResultDescriptor("job-new", "outputs/new.mp4"),
            new TimelinePosition(24000));

        Track created = inserted.Project.Tracks.Last();
        Assert.AreEqual("video", created.Type);
        Assert.IsFalse(created.Locked);
        Assert.AreEqual(24000L, created.Events.Single().Start.Samples);
    }

    [TestMethod]
    public void FromProject_RoundTripsExactSourceRangeAndClearsItWhenRemoved()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"source","name":"Source","meta":{"timeline":{"timebase":{"sample_rate":48000},"tracks":[{"id":"audio","type":"audio","clips":[{"id":"clip","start_sample":"0","end_sample":"48000","data":{"source_sample_rate":44100,"source_offset_sample":"9007199254740993","source_offset_remainder":"1/2","source_end_sample":"9007199254741993","source_end_remainder":"3/4","source_in_s":0,"source_out_s":0}}]}]}}}""",
            StudioJson.Options)!;

        CanonicalProject project = dto.CanonicalProject;
        SourceRange source = project.Tracks.Single().Events.Single().Source!;
        Assert.AreEqual(44_100, source.Start.SampleRate);
        Assert.AreEqual(9_007_199_254_740_993L, source.Start.Samples);
        Assert.AreEqual("1/2", source.Start.Remainder);

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(project);
        JsonNode data = rebuilt["tracks"]![0]!["clips"]![0]!["data"]!;
        Assert.AreEqual("9007199254740993", data["source_offset_sample"]!.GetValue<string>());
        Assert.AreEqual("3/4", data["source_end_remainder"]!.GetValue<string>());

        TimelineEvent cleared = project.Tracks[0].Events[0] with { Source = null };
        JsonObject withoutSource = ProjectTimelineContracts.RebuildTimeline(project with
        {
            Tracks = [project.Tracks[0] with { Events = [cleared] }]
        });
        Assert.IsNull(withoutSource["tracks"]![0]!["clips"]![0]!["data"]!["source_offset_sample"]);
        Assert.IsNull(withoutSource["tracks"]![0]!["clips"]![0]!["data"]!["source_in_s"]);
    }

    [TestMethod]
    public void FromProject_UsesLegacySourceSecondsAndRejectsBackwardsSourceRange()
    {
        ProjectDto legacy = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"legacy-source","name":"Legacy","meta":{"timeline":{"tracks":[{"id":"audio","clips":[{"id":"clip","start_s":0,"end_s":1,"data":{"source_sample_rate":44100,"source_in_s":1.25,"source_out_s":3.5}}]}]}}}""",
            StudioJson.Options)!;
        ProjectDto invalid = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"invalid-source","name":"Invalid","meta":{"timeline":{"tracks":[{"id":"audio","clips":[{"id":"clip","start_s":0,"end_s":1,"data":{"source_sample_rate":44100,"source_offset_sample":"2","source_offset_remainder":"1/2","source_end_sample":"2","source_end_remainder":"1/4"}}]}]}}}""",
            StudioJson.Options)!;

        SourceRange source = legacy.CanonicalProject.Tracks.Single().Events.Single().Source!;
        Assert.AreEqual(55_125L, source.Start.Samples);
        Assert.AreEqual(154_350L, source.End!.Samples);
        Assert.Throws<ArgumentException>(() => invalid.CanonicalProject);
    }

    [TestMethod]
    public void InsertRenderResult_PreservesTypedArtifactProvenanceAndLineage()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"provenance","name":"Provenance","revision":4,"meta":{"timeline":{"tracks":[{"id":"video","type":"video","clips":[]}]}}}""",
            StudioJson.Options)!;
        var descriptor = new RenderResultDescriptor(
            "job-provenance", "outputs/generated.mp4", 1,
            new JsonObject { ["manifest_path"] = "outputs/generated.mp4.artifact.json", ["content_hash"] = "sha256:abc" },
            "artifact-7", "comfyui", "local", "hunyuan-video", "r2", "4", "plan-3",
            ["artifact-parent"], ["audio-source"]);

        CanonicalTimelineInsertionResult inserted = RenderResultTimelineInsertion.Insert(dto.CanonicalProject, descriptor, new TimelinePosition(0));
        MediaAsset asset = inserted.Project.MediaAssets.Single();
        Assert.AreEqual("artifact-7", asset.VersionId);
        Assert.AreEqual("comfyui", asset.Provenance!.RendererId);
        Assert.AreEqual("artifact-parent", asset.Provenance.ParentArtifactIds.Single());

        using JsonDocument rebuiltDocument = JsonDocument.Parse(
            new JsonObject { ["timeline"] = ProjectTimelineContracts.RebuildTimeline(inserted.Project) }.ToJsonString());
        var roundTripDto = new ProjectDto
        {
            Id = dto.Id,
            Name = dto.Name,
            Revision = dto.Revision,
            SchemaVersion = dto.SchemaVersion,
            Meta = rebuiltDocument.RootElement.Clone()
        };
        MediaAsset roundTrip = roundTripDto.CanonicalProject.MediaAssets.Single();
        Assert.AreEqual("local", roundTrip.Provenance!.ProviderId);
        Assert.AreEqual("audio-source", roundTrip.Provenance.SourceAssetIds.Single());
    }

    [TestMethod]
    public void FromProject_MergesProjectAndTimelineMediaPoolsWithTimelineWinning()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"merged-pool","name":"Merged","meta":{"media_pool":[{"id":"existing","path":"old.mp4","kind":"video"}],"timeline":{"media_pool":[{"id":"existing","path":"updated.mp4","kind":"video"},{"id":"inserted","path":"inserted.mp4","kind":"video"}],"tracks":[]}}}""",
            StudioJson.Options)!;

        CanonicalProject project = dto.CanonicalProject;

        Assert.AreEqual(2, project.MediaAssets.Count);
        Assert.AreEqual("updated.mp4", project.MediaAssets.Single(asset => asset.Id == "existing").Path);
        Assert.AreEqual("inserted.mp4", project.MediaAssets.Single(asset => asset.Id == "inserted").Path);
    }

    [TestMethod]
    public void RenderResultDescriptor_FromJobNormalizesResultAndPayloadProvenance()
    {
        StudioJob job = JsonSerializer.Deserialize<StudioJob>(
            """{"id":"job-queue","project_id":"project","type":"render","status":"succeeded","result":{"artifact_id":"artifact-job","engine":"comfyui","model":{"id":"hunyuan-video","revision":"r3"},"lineage":{"parents":["parent-job"]}},"payload":{"provider_id":"local","plan_revision":"plan-9","source_assets":[{"id":"audio-job"}]}}""",
            StudioJson.Options)!;

        CanonicalProject project = JsonSerializer.Deserialize<ProjectDto>(
            """{"id":"project","name":"Project","meta":{"timeline":{"tracks":[{"id":"video","type":"video","clips":[]}]}}}""",
            StudioJson.Options)!.CanonicalProject;
        CanonicalTimelineInsertionResult inserted = RenderResultTimelineInsertion.Insert(
            project, RenderResultDescriptor.FromJob(job, "outputs/job.mp4"), new TimelinePosition(0));

        ArtifactProvenance provenance = inserted.Project.MediaAssets.Single().Provenance!;
        Assert.AreEqual("artifact-job", provenance.ArtifactId);
        Assert.AreEqual("comfyui", provenance.RendererId);
        Assert.AreEqual("local", provenance.ProviderId);
        Assert.AreEqual("hunyuan-video", provenance.ModelId);
        Assert.AreEqual("r3", provenance.ModelRevision);
        Assert.AreEqual("plan-9", provenance.PlanRevision);
        Assert.AreEqual("parent-job", provenance.ParentArtifactIds.Single());
        Assert.AreEqual("audio-job", provenance.SourceAssetIds.Single());
    }
}
