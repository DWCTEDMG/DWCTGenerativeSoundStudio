using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ProfessionalEditingTests
{
    [TestMethod]
    public void Read_PreservesExtensionsAndExactInt64Samples()
    {
        CanonicalProject project=Project("\"editing\":{\"schema_version\":1,\"vendor\":{\"x\":1},\"automation_lanes\":[{\"id\":\"gain\",\"track_id\":\"track\",\"target\":\"volume\",\"mode\":\"touch\",\"min_value\":0,\"max_value\":2,\"custom\":true,\"points\":[{\"id\":\"p\",\"sample\":\"9007199254740993\",\"value\":1.5,\"curve\":\"smooth\",\"tension\":0.25,\"note\":\"keep\"}]}],\"takes\":[],\"comp_ranges\":[]}");
        ProfessionalEditingDocument editing=ProfessionalEditingContracts.Read(project.Timeline);
        Assert.AreEqual(9007199254740993,editing.AutomationLanes[0].Points[0].Sample);
        Assert.AreEqual("keep",editing.AutomationLanes[0].Points[0].Metadata["note"]!.GetValue<string>());
        Assert.AreEqual(1,ProjectTimelineContracts.RebuildTimeline(project)["editing"]!["vendor"]!["x"]!.GetValue<int>());
    }

    [TestMethod]
    public void Read_LegacyDoesNotMutateAndRejectsInvalidData()
    {
        JsonObject timeline=new();
        ProfessionalEditingDocument legacy=ProfessionalEditingContracts.Read(timeline);
        Assert.IsNull(timeline["editing"]); Assert.IsEmpty(legacy.AutomationLanes);
        Assert.Throws<InvalidDataException>(()=>ProfessionalEditingContracts.Read(JsonNode.Parse("{\"editing\":{\"schema_version\":2}}")!.AsObject()));
        Assert.Throws<InvalidDataException>(()=>Project("\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"t\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"}],\"comp_ranges\":[{\"id\":\"c\",\"clip_id\":\"clip\",\"take_id\":\"missing\",\"start_sample\":\"0\",\"end_sample\":\"10\"}]}"));
    }

    [TestMethod]
    public void Read_ValidatesTakeSourceActiveTakeFadesAndProcess()
    {
        CanonicalProject project=Project("\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\",\"kind\":\"audio\"}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"take\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\",\"source_range\":{\"sample_rate\":44100,\"start_sample\":\"9007199254740993\",\"start_remainder\":\"1/2\",\"end_sample\":\"9007199254741993\",\"end_remainder\":\"-1/2\"}}],\"comp_ranges\":[]}");
        JsonObject clip=project.Timeline["tracks"]![0]!["clips"]![1]!.AsObject();
        clip["data"]=JsonNode.Parse("{\"active_take_id\":\"take\",\"fades\":{\"in_samples\":\"10\",\"out_samples\":\"20\",\"curve\":\"s_curve\",\"vendor\":true},\"process\":{\"playback_rate\":1.25,\"stretch_ratio\":0.8,\"algorithm\":\"phase_vocoder\"}}")!;
        ProfessionalEditingDocument document=ProfessionalEditingContracts.Read(project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(project,document);
        Assert.AreEqual(9007199254740993,document.Takes[0].Source!.Start.Samples);
        Assert.AreEqual(FadeCurve.SCurve,document.Clips[0].Fades!.Curve);
        Assert.AreEqual(ProcessAlgorithm.PhaseVocoder,document.Clips[0].Process!.Algorithm);
    }

    [TestMethod]
    public void SourceRange_RejectsInvertedSameSampleRemainders()
    {
        SourcePosition start=new(48000,10,"1/2");
        SourcePosition end=new(48000,10,"-1/2");

        Assert.Throws<ArgumentException>(()=>new SourceRange(start,end));
    }

    [TestMethod]
    public void Operations_CoverAutomationTakesProcessAndAdvancedEditing()
    {
        CanonicalProject p=Project("\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\",\"kind\":\"audio\"}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[{\"id\":\"gain\",\"track_id\":\"track\",\"target\":\"volume\",\"mode\":\"read\",\"min_value\":0,\"max_value\":2,\"points\":[]}],\"takes\":[],\"comp_ranges\":[]}");
        Assert.AreEqual("upsert_automation_point",ProfessionalEditingOperations.UpsertAutomationPoint(p,"gain","p",12,1).GetValue<string>("kind"));
        Assert.AreEqual("write",ProfessionalEditingOperations.SetAutomationMode(p,"gain",AutomationMode.Write).GetValue<string>("mode"));
        Assert.AreEqual("add_take",ProfessionalEditingOperations.AddTake(p,"track","clip","take","asset").GetValue<string>("kind"));
        Assert.AreEqual("set_process",ProfessionalEditingOperations.SetProcess(p,"track","clip",1.5,0.75).GetValue<string>("kind"));
        Assert.AreEqual("set_fades",ProfessionalEditingOperations.SetFades(p,"track","clip",10,20).GetValue<string>("kind"));
        Assert.AreEqual("nudge",ProfessionalEditingOperations.Nudge(p,"track","clip",-3).GetValue<string>("kind"));
        Assert.AreEqual("ripple",ProfessionalEditingOperations.Ripple(p,"track",0,10).GetValue<string>("kind"));
        Assert.AreEqual("slip",ProfessionalEditingOperations.Slip(p,"track","clip",4).GetValue<string>("kind"));
        Assert.AreEqual("slide",ProfessionalEditingOperations.Slide(p,"track","clip",4).GetValue<string>("kind"));
        Assert.AreEqual("range_edit",ProfessionalEditingOperations.RangeEdit(p,"track",0,100,"move",2).GetValue<string>("kind"));
        Assert.Throws<ArgumentOutOfRangeException>(()=>ProfessionalEditingOperations.SetFades(p,"track","clip",30_000,30_000));
    }

    [TestMethod]
    public void AutomationSnapshot_InterpolatesWithoutLookupAllocations()
    {
        var points=ImmutableArray.Create(new AutomationSamplePoint(10,0,AutomationCurve.Step,0),new AutomationSamplePoint(20,1,AutomationCurve.Linear,0),new AutomationSamplePoint(30,0,AutomationCurve.Smooth,0));
        var lane=new AutomationLaneSnapshot("lane","track","send:verb",AutomationMode.Read,.5,points);
        Assert.AreEqual(.5,lane.Evaluate(0)); Assert.AreEqual(0,lane.Evaluate(15)); Assert.AreEqual(.5,lane.Evaluate(25),1e-12); Assert.AreEqual(0,lane.Evaluate(30));
        Assert.Throws<ArgumentException>(()=>new AutomationLaneSnapshot("lane","track","volume",AutomationMode.Read,0,
            ImmutableArray.Create(new AutomationSamplePoint(1,0,(AutomationCurve)99,0))));
        Assert.Throws<ArgumentOutOfRangeException>(()=>new AutomationLaneSnapshot("lane","track","volume",(AutomationMode)99,0,[]));
    }

    [TestMethod]
    public void Operations_RejectLockedTrackAndClip()
    {
        CanonicalProject trackLocked=Project("", "true", "false");
        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.AddAutomationLane(trackLocked,"x","track","pan",AutomationMode.Read,-1,1));
        CanonicalProject clipLocked=Project("", "false", "true");
        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.Nudge(clipLocked,"track","clip",1));
    }

    [TestMethod]
    public void RangeDuplicate_EmitsDeterministicEditingIdsAndRejectsInvalidSets()
    {
        CanonicalProject project=Project("\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\",\"kind\":\"audio\"}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"take\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"}],\"comp_ranges\":[{\"id\":\"comp\",\"clip_id\":\"clip\",\"take_id\":\"take\",\"start_sample\":\"50000\",\"end_sample\":\"60000\"}]}");

        JsonObject operation=ProfessionalEditingOperations.RangeEdit(project,"track",48000,96000,"duplicate",100000,
            ["copy"],["copy-take"],["copy-comp"]);

        CollectionAssert.AreEqual(new[]{"copy"},operation["new_ids"]!.AsArray().Select(node=>node!.GetValue<string>()).ToArray());
        CollectionAssert.AreEqual(new[]{"copy-take"},operation["new_take_ids"]!.AsArray().Select(node=>node!.GetValue<string>()).ToArray());
        CollectionAssert.AreEqual(new[]{"copy-comp"},operation["new_comp_ids"]!.AsArray().Select(node=>node!.GetValue<string>()).ToArray());
        Assert.Throws<ArgumentException>(()=>ProfessionalEditingOperations.RangeEdit(project,"track",48000,96000,"duplicate",1,["copy"],[],["copy-comp"]));
        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.RangeEdit(project,"track",48000,96000,"duplicate",1,["copy"],["take"],["copy-comp"]));
        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.RangeEdit(project,"track",48000,96000,"duplicate",1,["copy"],["same"],["same"]));
        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.RangeEdit(project,"track",48000,96000,"duplicate",1,["asset"],["copy-take"],["copy-comp"]));
    }

    [TestMethod]
    public void ExistingCompAndCrossfadeIds_CannotChangeOwners()
    {
        CanonicalProject project=ProjectWithOwnedEditingIds();

        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.SetCompRange(
            project,"track","clip","owned-comp","take-b",90,100));
        Assert.Throws<InvalidOperationException>(()=>ProfessionalEditingOperations.SetCrossfade(
            project,"track","clip","right",160,170,FadeCurve.Linear,"owned-xf"));
        Assert.AreEqual("set_comp_range",ProfessionalEditingOperations.SetCompRange(
            project,"track","left","owned-comp","take-a",10,30).GetValue<string>("kind"));
        Assert.AreEqual("set_crossfade",ProfessionalEditingOperations.SetCrossfade(
            project,"track","left","clip",85,95,FadeCurve.EqualPower,"owned-xf").GetValue<string>("kind"));
    }

    private static CanonicalProject ProjectWithOwnedEditingIds()
    {
        const string json="{\"id\":\"p\",\"name\":\"P\",\"revision\":1,\"schema_version\":1,\"meta\":{\"timeline\":{\"timebase\":{\"sample_rate\":48000},\"media_pool\":[{\"id\":\"asset\",\"path\":\"a.wav\"}],\"tracks\":[{\"id\":\"track\",\"type\":\"audio\",\"clips\":[{\"id\":\"left\",\"start_sample\":\"0\",\"end_sample\":\"100\"},{\"id\":\"clip\",\"start_sample\":\"80\",\"end_sample\":\"180\"},{\"id\":\"right\",\"start_sample\":\"160\",\"end_sample\":\"260\"}]}],\"editing\":{\"schema_version\":1,\"automation_lanes\":[],\"takes\":[{\"id\":\"take-a\",\"clip_id\":\"left\",\"media_asset_id\":\"asset\"},{\"id\":\"take-b\",\"clip_id\":\"clip\",\"media_asset_id\":\"asset\"}],\"comp_ranges\":[{\"id\":\"owned-comp\",\"clip_id\":\"left\",\"take_id\":\"take-a\",\"start_sample\":\"10\",\"end_sample\":\"20\"}],\"crossfades\":[{\"id\":\"owned-xf\",\"track_id\":\"track\",\"left_clip_id\":\"left\",\"right_clip_id\":\"clip\",\"start_sample\":\"80\",\"end_sample\":\"100\"}]}}}}";
        return JsonSerializer.Deserialize<ProjectDto>(json,StudioJson.Options)!.CanonicalProject;
    }

    private static CanonicalProject Project(string extra,string trackLocked="false",string clipLocked="false")
    {
        string comma=string.IsNullOrEmpty(extra)?"":extra+",";
        ProjectDto dto=JsonSerializer.Deserialize<ProjectDto>("{\"id\":\"p\",\"name\":\"P\",\"revision\":1,\"schema_version\":1,\"meta\":{\"timeline\":{"+comma+"\"timebase\":{\"sample_rate\":48000},\"tracks\":[{\"id\":\"track\",\"type\":\"audio\",\"locked\":"+trackLocked+",\"clips\":[{\"id\":\"left\",\"start_sample\":\"0\",\"end_sample\":\"48000\"},{\"id\":\"clip\",\"locked\":"+clipLocked+",\"start_sample\":\"48000\",\"end_sample\":\"96000\"},{\"id\":\"right\",\"start_sample\":\"96000\",\"end_sample\":\"144000\"}]}]}}}",StudioJson.Options)!;
        return dto.CanonicalProject;
    }
}

internal static class JsonTestExtensions { public static T GetValue<T>(this JsonObject value,string name)=>value[name]!.GetValue<T>(); }
