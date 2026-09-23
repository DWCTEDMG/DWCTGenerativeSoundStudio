#include "public.sdk/source/vst/hosting/eventlist.h"
#include "public.sdk/source/vst/hosting/hostclasses.h"
#include "public.sdk/source/vst/hosting/module.h"
#include "public.sdk/source/vst/hosting/parameterchanges.h"
#include "public.sdk/source/vst/hosting/plugprovider.h"
#include "public.sdk/source/vst/hosting/processdata.h"
#include "public.sdk/source/vst/utility/memoryibstream.h"
#include "public.sdk/source/vst/utility/stringconvert.h"
#include "pluginterfaces/gui/iplugview.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include "pluginterfaces/vst/ivsteditcontroller.h"
#include "pluginterfaces/vst/ivstunits.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using namespace Steinberg;
using namespace Steinberg::Vst;

namespace Steinberg { FUnknown* gStandardPluginContext = new Vst::HostApplication (); }

namespace {
constexpr int kSchemaVersion = 1;

std::string jsonEscape (const std::string& value)
{
	std::ostringstream out;
	for (unsigned char c : value)
	{
		switch (c)
		{
			case '\\': out << "\\\\"; break;
			case '"': out << "\\\""; break;
			case '\b': out << "\\b"; break;
			case '\f': out << "\\f"; break;
			case '\n': out << "\\n"; break;
			case '\r': out << "\\r"; break;
			case '\t': out << "\\t"; break;
			default:
				if (c < 0x20) out << "\\u00" << "0123456789abcdef"[(c >> 4) & 0xf] << "0123456789abcdef"[c & 0xf];
				else out << static_cast<char> (c);
		}
	}
	return out.str ();
}

std::string quote (const std::string& value) { return "\"" + jsonEscape (value) + "\""; }

struct Arguments
{
	std::string operation;
	std::string modulePath;
	std::string pluginId;
	std::string fingerprintPath;
	std::string fingerprintSha;
	int64 fingerprintLength {};
	int64 fingerprintTicks {};
	int32 sampleRate {48000};
	int32 frames {256};
	std::string requestPath;
	std::string responsePath;
};

bool parseInt64 (const std::string& text, int64& value)
{
	try { size_t used {}; value = std::stoll (text, &used); return used == text.size (); }
	catch (...) { return false; }
}

bool parseArguments (int argc, wchar_t** argv, Arguments& result, std::string& error)
{
	if (argc < 2) { error = "Missing operation."; return false; }
	result.operation = Vst::StringConvert::convert (wscast (argv[1]));
	for (int i = 2; i < argc; ++i)
	{
		std::string key = Vst::StringConvert::convert (wscast (argv[i]));
		if (i + 1 >= argc) { error = "Missing value for " + key + "."; return false; }
		std::string value = Vst::StringConvert::convert (wscast (argv[++i]));
		if (key == "--module") result.modulePath = value;
		else if (key == "--plugin-id") result.pluginId = value;
		else if (key == "--fingerprint-path") result.fingerprintPath = value;
		else if (key == "--fingerprint-sha256") result.fingerprintSha = value;
		else if (key == "--fingerprint-length") { if (!parseInt64 (value, result.fingerprintLength)) { error = "Invalid fingerprint length."; return false; } }
		else if (key == "--fingerprint-ticks") { if (!parseInt64 (value, result.fingerprintTicks)) { error = "Invalid fingerprint ticks."; return false; } }
		else if (key == "--sample-rate") { int64 parsed {}; if (!parseInt64 (value, parsed) || parsed < 8000 || parsed > 384000) { error = "Invalid sample rate."; return false; } result.sampleRate = static_cast<int32> (parsed); }
		else if (key == "--frames") { int64 parsed {}; if (!parseInt64 (value, parsed) || parsed < 1 || parsed > 16384) { error = "Invalid frame count."; return false; } result.frames = static_cast<int32> (parsed); }
		else if (key == "--request-pipe") result.requestPath = value;
		else if (key == "--response-pipe") result.responsePath = value;
		else if (key == "--format" && value == "json-v1") {}
		else { error = "Unknown argument " + key + "."; return false; }
	}
	if (result.operation == "--worker")
	{
		if (result.requestPath.empty () || result.responsePath.empty ()) { error = "Worker request and response pipes are required."; return false; }
	}
	else if (result.modulePath.empty ()) { error = "A module path is required."; return false; }
	return true;
}

int32 countChannels (IComponent& component, BusDirection direction)
{
	int32 channels = 0;
	for (int32 index = 0; index < component.getBusCount (kAudio, direction); ++index)
	{
		BusInfo info {};
		if (component.getBusInfo (kAudio, direction, index, info) == kResultTrue && info.busType == kMain)
			channels += std::max<int32> (0, info.channelCount);
	}
	return channels;
}

int32 countEventBuses (IComponent& component, BusDirection direction)
{
	return std::max<int32> (0, component.getBusCount (kEvent, direction));
}

bool hasEditor (IEditController* controller)
{
	if (!controller) return false;
	IPlugView* view = controller->createView (ViewType::kEditor);
	if (!view) return false;
	view->release ();
	return true;
}

bool supportsPresets (IEditController* controller)
{
	FUnknownPtr<IUnitInfo> units (controller);
	return units && units->getProgramListCount () > 0;
}

std::string classId (const VST3::Hosting::ClassInfo& info) { return info.ID ().toString (); }

std::string parameterTitle (const String128 value)
{
	return Vst::StringConvert::convert (value);
}

VST3::Hosting::Module::Ptr loadModule (const std::string& path)
{
	std::string error;
	auto module = VST3::Hosting::Module::create (path, error);
	if (!module) throw std::runtime_error (error.empty () ? "Module load failed." : error);
	return module;
}

void printFailure (const std::string& diagnostic)
{
	std::cerr << "{\"schemaVersion\":" << kSchemaVersion << ",\"success\":false,\"diagnostic\":"
				<< quote (diagnostic) << "}" << std::endl;
}

int scanModule (const Arguments& args)
{
	auto module = loadModule (args.modulePath);
	auto factory = module->getFactory ();
	std::ostringstream plugins;
	bool first = true;
	for (const auto& info : factory.classInfos ())
	{
		if (info.category () != kVstAudioEffectClass) continue;
		PlugProvider provider (factory, info, true);
		if (!provider.initialize ()) throw std::runtime_error ("Failed to initialize " + info.name () + ".");
		auto component = provider.getComponentPtr ();
		auto controller = provider.getControllerPtr ();
		FUnknownPtr<IAudioProcessor> processor (component);
		if (!processor) throw std::runtime_error ("The class does not expose IAudioProcessor.");
		if (!first) plugins << ',';
		first = false;
		plugins << "{\"pluginId\":" << quote (classId (info))
				<< ",\"name\":" << quote (info.name ())
				<< ",\"vendor\":" << quote (info.vendor ())
				<< ",\"version\":" << quote (info.version ())
				<< ",\"category\":" << quote (info.subCategoriesString ())
				<< ",\"audioInputs\":" << countChannels (*component, kInput)
				<< ",\"audioOutputs\":" << countChannels (*component, kOutput)
				<< ",\"hasEditor\":" << (hasEditor (controller) ? "true" : "false")
				<< ",\"supportsPresets\":" << (supportsPresets (controller) ? "true" : "false")
				<< ",\"reportedLatencySamples\":" << processor->getLatencySamples () << '}';
		std::string capabilities = "audio";
		if (countEventBuses (*component, kInput) > 0) capabilities += ",midi-input";
		if (countEventBuses (*component, kOutput) > 0) capabilities += ",midi-output";
		if (controller && controller->getParameterCount () > 0) capabilities += ",parameters";
		if (hasEditor (controller)) capabilities += ",editor";
		std::string row = plugins.str ();
		plugins.str (""); plugins.clear ();
		plugins << row.substr (0, row.size () - 1)
				<< ",\"eventInputBuses\":" << countEventBuses (*component, kInput)
				<< ",\"eventOutputBuses\":" << countEventBuses (*component, kOutput)
				<< ",\"parameterCount\":" << (controller ? controller->getParameterCount () : 0)
				<< ",\"architecture\":\"x64\",\"capabilities\":" << quote (capabilities) << '}';
	}
	const bool supported = !first;
	std::cout << "{\"schemaVersion\":" << kSchemaVersion
				<< ",\"fingerprint\":{\"modulePath\":" << quote (args.fingerprintPath)
				<< ",\"length\":" << args.fingerprintLength
				<< ",\"lastWriteUtcTicks\":" << args.fingerprintTicks
				<< ",\"sha256\":" << quote (args.fingerprintSha)
				<< "},\"plugins\":[" << plugins.str () << "]"
				<< ",\"status\":" << quote (supported ? "success" : "unsupported") << "}" << std::endl;
	return 0;
}

struct ActivePlugin
{
	VST3::Hosting::Module::Ptr module;
	std::unique_ptr<PlugProvider> provider;
	IPtr<IComponent> component;
	IPtr<IEditController> controller;
	IPtr<IAudioProcessor> processor;
	HostProcessData data;
	ParameterChanges inputChanges;
	ParameterChanges outputChanges;
	EventList inputEvents;
	EventList outputEvents;
	ProcessContext context {};
	std::vector<ParameterInfo> parameters;
	int32 maximumFrames {};
	int32 mainInputBus {-1};
	int32 mainOutputBus {-1};
	int32 eventInputBus {-1};
	bool componentActive {};
	bool processing {};

	~ActivePlugin ()
	{
		if (processing) processor->setProcessing (false);
		if (componentActive) component->setActive (false);
	}
};

std::unique_ptr<ActivePlugin> createPlugin (const Arguments& args)
{
	auto result = std::make_unique<ActivePlugin> ();
	result->module = loadModule (args.modulePath);
	auto factory = result->module->getFactory ();
	VST3::Hosting::ClassInfo selected;
	bool found = false;
	for (const auto& info : factory.classInfos ())
	{
		if (info.category () != kVstAudioEffectClass) continue;
		if (!args.pluginId.empty () && classId (info) != args.pluginId) continue;
		selected = info; found = true; break;
	}
	if (!found) throw std::runtime_error ("The requested audio effect class was not found.");
	result->provider = std::make_unique<PlugProvider> (factory, selected, true);
	if (!result->provider->initialize ()) throw std::runtime_error ("Plug-in initialization failed.");
	result->component = result->provider->getComponentPtr ();
	result->controller = result->provider->getControllerPtr ();
	result->processor = FUnknownPtr<IAudioProcessor> (result->component);
	if (!result->processor) throw std::runtime_error ("The plug-in does not expose IAudioProcessor.");

	for (BusDirection direction : {kInput, kOutput})
		for (int32 index = 0; index < result->component->getBusCount (kAudio, direction); ++index)
		{
			BusInfo info {};
			if (result->component->getBusInfo (kAudio, direction, index, info) == kResultTrue)
			{
				bool main = info.busType == kMain;
				result->component->activateBus (kAudio, direction, index, main);
				if (main && direction == kInput && result->mainInputBus < 0) result->mainInputBus = index;
				if (main && direction == kOutput && result->mainOutputBus < 0) result->mainOutputBus = index;
			}
		}
	for (int32 index = 0; index < result->component->getBusCount (kEvent, kInput); ++index)
	{
		BusInfo info {};
		if (result->component->getBusInfo (kEvent, kInput, index, info) != kResultTrue) continue;
		if (result->eventInputBus < 0 || info.busType == kMain) result->eventInputBus = index;
		if (info.busType == kMain) break;
	}
	for (int32 index = 0; index < result->component->getBusCount (kEvent, kInput); ++index)
	{
		const bool activate = index == result->eventInputBus;
		if (result->component->activateBus (kEvent, kInput, index, activate) != kResultTrue && activate)
			throw std::runtime_error ("The selected event input bus could not be activated.");
	}

	std::vector<SpeakerArrangement> inputArrangements;
	std::vector<SpeakerArrangement> outputArrangements;
	for (BusDirection direction : {kInput, kOutput})
	{
		auto& arrangements = direction == kInput ? inputArrangements : outputArrangements;
		for (int32 index = 0; index < result->component->getBusCount (kAudio, direction); ++index)
		{
			BusInfo info {};
			if (result->component->getBusInfo (kAudio, direction, index, info) != kResultTrue || info.busType != kMain) continue;
			SpeakerArrangement arrangement {};
			if (result->processor->getBusArrangement (direction, index, arrangement) != kResultTrue)
				throw std::runtime_error ("Main audio bus arrangement query failed.");
			arrangements.push_back (arrangement);
		}
	}
	if (result->processor->setBusArrangements (
			inputArrangements.empty () ? nullptr : inputArrangements.data (), static_cast<int32> (inputArrangements.size ()),
			outputArrangements.empty () ? nullptr : outputArrangements.data (), static_cast<int32> (outputArrangements.size ())) != kResultTrue)
		throw std::runtime_error ("Main audio bus arrangement negotiation failed.");
	ProcessSetup setup {kRealtime, kSample32, args.frames, static_cast<SampleRate> (args.sampleRate)};
	if (result->processor->setupProcessing (setup) != kResultTrue)
		throw std::runtime_error ("Float32 process setup failed.");
	if (!result->data.prepare (*result->component, args.frames, kSample32))
		throw std::runtime_error ("Audio process buffers could not be prepared.");
	result->maximumFrames = args.frames;
	if (result->component->setActive (true) != kResultTrue)
		throw std::runtime_error ("The plug-in component could not become active.");
	result->componentActive = true;
	const tresult processingResult = result->processor->setProcessing (true);
	if (processingResult != kResultOk && processingResult != kNotImplemented)
		throw std::runtime_error ("The plug-in processor could not enter the processing state.");
	result->processing = true;
	int32 parameterCount = result->controller ? result->controller->getParameterCount () : 0;
	result->inputChanges.setMaxParameters (parameterCount);
	result->outputChanges.setMaxParameters (parameterCount);
	for (int32 index = 0; index < parameterCount; ++index)
	{
		ParameterInfo parameter {};
		if (result->controller->getParameterInfo (index, parameter) == kResultTrue) result->parameters.push_back (parameter);
	}
	result->context.state = ProcessContext::kPlaying | ProcessContext::kTempoValid | ProcessContext::kTimeSigValid;
	result->context.sampleRate = args.sampleRate;
	result->context.tempo = 120.;
	result->context.timeSigNumerator = 4;
	result->context.timeSigDenominator = 4;
	result->data.inputParameterChanges = &result->inputChanges;
	result->data.outputParameterChanges = &result->outputChanges;
	result->data.inputEvents = &result->inputEvents;
	result->data.outputEvents = &result->outputEvents;
	result->data.processContext = &result->context;
	return result;
}

int qualify (const Arguments& args)
{
	auto plugin = createPlugin (args);
	int32 parameterCount = plugin->controller ? plugin->controller->getParameterCount () : 0;
	bool parameterChanged = false;
	if (parameterCount > 0)
	{
		ParameterInfo parameter {};
		if (plugin->controller->getParameterInfo (0, parameter) != kResultTrue)
			throw std::runtime_error ("Parameter enumeration failed.");
		double initial = plugin->controller->getParamNormalized (parameter.id);
		double changed = initial < 0.5 ? 0.75 : 0.25;
		plugin->controller->setParamNormalized (parameter.id, changed);
		int32 queueIndex {};
		IParamValueQueue* queue = plugin->inputChanges.addParameterData (parameter.id, queueIndex);
		int32 pointIndex {};
		if (!queue || queue->addPoint (0, changed, pointIndex) != kResultTrue)
			throw std::runtime_error ("Parameter change queueing failed.");
		parameterChanged = true;
	}
	plugin->data.numSamples = args.frames;
	plugin->data.processMode = kRealtime;
	plugin->data.symbolicSampleSize = kSample32;
	for (int32 bus = 0; bus < plugin->data.numInputs; ++bus)
		for (int32 channel = 0; channel < plugin->data.inputs[bus].numChannels; ++channel)
		{
			auto* samples = plugin->data.inputs[bus].channelBuffers32[channel];
			std::fill_n (samples, args.frames, 0.f);
			samples[0] = channel == 0 ? 1.f : 0.5f;
		}
	for (int32 bus = 0; bus < plugin->data.numOutputs; ++bus)
		for (int32 channel = 0; channel < plugin->data.outputs[bus].numChannels; ++channel)
			std::fill_n (plugin->data.outputs[bus].channelBuffers32[channel], args.frames, 0.f);
	if (plugin->processor->process (plugin->data) != kResultTrue)
		throw std::runtime_error ("The plug-in rejected the process block.");
	double checksum = 0;
	bool finite = true;
	for (int32 bus = 0; bus < plugin->data.numOutputs; ++bus)
		for (int32 channel = 0; channel < plugin->data.outputs[bus].numChannels; ++channel)
			for (int32 frame = 0; frame < args.frames; ++frame)
			{
				float sample = plugin->data.outputs[bus].channelBuffers32[channel][frame];
				finite = finite && std::isfinite (sample);
				checksum += std::abs (static_cast<double> (sample));
			}
	if (!finite) throw std::runtime_error ("The plug-in produced non-finite samples.");

	ResizableMemoryIBStream state (4096);
	if (plugin->component->getState (&state) != kResultTrue)
		throw std::runtime_error ("Component state capture failed.");
	auto saved = state.take ();
	ResizableMemoryIBStream restore (saved.size ());
	int32 written {};
	if (!saved.empty () && restore.write (saved.data (), static_cast<int32> (saved.size ()), &written) != kResultTrue)
		throw std::runtime_error ("Component state buffering failed.");
	restore.rewind ();
	if (plugin->component->setState (&restore) != kResultTrue)
		throw std::runtime_error ("Component state restore failed.");
	size_t controllerStateBytes = 0;
	if (plugin->controller)
	{
		restore.rewind ();
		if (plugin->controller->setComponentState (&restore) != kResultTrue)
			throw std::runtime_error ("Controller state synchronization failed.");
		ResizableMemoryIBStream controllerState (4096);
		if (plugin->controller->getState (&controllerState) == kResultTrue)
		{
			auto savedController = controllerState.take ();
			controllerStateBytes = savedController.size ();
			ResizableMemoryIBStream restoreController (savedController.size ());
			int32 controllerWritten {};
			if (!savedController.empty () && restoreController.write (savedController.data (), static_cast<int32> (savedController.size ()), &controllerWritten) != kResultTrue)
				throw std::runtime_error ("Controller state buffering failed.");
			restoreController.rewind ();
			if (plugin->controller->setState (&restoreController) != kResultTrue)
				throw std::runtime_error ("Controller state restore failed.");
		}
	}

	std::cout << "{\"schemaVersion\":" << kSchemaVersion
				<< ",\"success\":true,\"audioInputs\":" << countChannels (*plugin->component, kInput)
				<< ",\"audioOutputs\":" << countChannels (*plugin->component, kOutput)
				<< ",\"latencySamples\":" << plugin->processor->getLatencySamples ()
				<< ",\"parameterCount\":" << parameterCount
				<< ",\"parameterChanged\":" << (parameterChanged ? "true" : "false")
				<< ",\"stateBytes\":" << saved.size ()
				<< ",\"controllerStateBytes\":" << controllerStateBytes
				<< ",\"outputChecksum\":" << checksum
				<< ",\"finite\":true,\"diagnostic\":\"Native VST3 lifecycle, parameter, state, and float32 process block completed.\"}" << std::endl;
	return 0;
}

enum class WorkerOperation : uint32_t { Ping = 1, Process = 2, SetParameter = 3, GetState = 4, SetState = 5, Shutdown = 6, Crash = 7, Hang = 8, QueueMidiEvents = 9 };
struct WorkerHeader { uint32_t magic; uint32_t version; uint32_t operation; uint32_t requestId; uint32_t payloadBytes; };
struct WorkerResponseHeader { uint32_t magic; uint32_t version; uint32_t status; uint32_t requestId; uint32_t payloadBytes; uint32_t diagnosticBytes; };
constexpr uint32_t kWorkerMagic = 0x33475456;
constexpr uint32_t kWorkerVersion = 1;
constexpr uint32_t kMaximumWorkerPayload = 16 * 1024 * 1024;

template <typename T> bool readValue (std::istream& input, T& value)
{
	input.read (reinterpret_cast<char*> (&value), sizeof (value));
	return input.good ();
}

template <typename T> void appendValue (std::vector<uint8_t>& output, const T& value)
{
	const auto* bytes = reinterpret_cast<const uint8_t*> (&value);
	output.insert (output.end (), bytes, bytes + sizeof (value));
}

bool readBytes (std::istream& input, std::vector<uint8_t>& value, uint32_t count)
{
	value.resize (count);
	if (count > 0) input.read (reinterpret_cast<char*> (value.data ()), count);
	return input.good ();
}

void writeResponse (std::ostream& output, uint32_t requestId, bool success, const std::vector<uint8_t>& payload, const std::string& diagnostic)
{
	WorkerResponseHeader header {kWorkerMagic, kWorkerVersion, success ? 0u : 1u, requestId,
		static_cast<uint32_t> (payload.size ()), static_cast<uint32_t> (diagnostic.size ())};
	output.write (reinterpret_cast<const char*> (&header), sizeof (header));
	if (!payload.empty ()) output.write (reinterpret_cast<const char*> (payload.data ()), payload.size ());
	if (!diagnostic.empty ()) output.write (diagnostic.data (), diagnostic.size ());
	output.flush ();
}

std::vector<uint8_t> captureState (ActivePlugin& plugin)
{
	ResizableMemoryIBStream componentStream (4096);
	if (plugin.component->getState (&componentStream) != kResultTrue) throw std::runtime_error ("Component state capture failed.");
	auto componentState = componentStream.take ();
	std::vector<uint8_t> controllerState;
	if (plugin.controller)
	{
		ResizableMemoryIBStream controllerStream (4096);
		if (plugin.controller->getState (&controllerStream) == kResultTrue)
		{
			auto captured = controllerStream.take ();
			controllerState.assign (captured.begin (), captured.end ());
		}
	}
	std::vector<uint8_t> payload;
	appendValue (payload, static_cast<uint32_t> (0x31545356)); // VST1
	appendValue (payload, static_cast<uint32_t> (componentState.size ()));
	appendValue (payload, static_cast<uint32_t> (controllerState.size ()));
	payload.insert (payload.end (), componentState.begin (), componentState.end ());
	payload.insert (payload.end (), controllerState.begin (), controllerState.end ());
	return payload;
}

void restoreState (ActivePlugin& plugin, const std::vector<uint8_t>& state)
{
	if (state.size () < 3 * sizeof (uint32_t)) throw std::runtime_error ("VST3 state payload is truncated.");
	uint32_t magic {}, componentBytes {}, controllerBytes {};
	std::memcpy (&magic, state.data (), sizeof (magic));
	std::memcpy (&componentBytes, state.data () + sizeof (magic), sizeof (componentBytes));
	std::memcpy (&controllerBytes, state.data () + 2 * sizeof (uint32_t), sizeof (controllerBytes));
	if (magic != 0x31545356 || state.size () != 3 * sizeof (uint32_t) + static_cast<size_t> (componentBytes) + controllerBytes)
		throw std::runtime_error ("VST3 state payload has an unsupported format.");
	const auto* componentData = state.data () + 3 * sizeof (uint32_t);
	ResizableMemoryIBStream stream (componentBytes);
	int32 written {};
	if (componentBytes > 0 && stream.write (const_cast<uint8_t*> (componentData), static_cast<int32> (componentBytes), &written) != kResultTrue)
		throw std::runtime_error ("Component state buffering failed.");
	stream.rewind ();
	if (plugin.component->setState (&stream) != kResultTrue) throw std::runtime_error ("Component state restore failed.");
	if (plugin.controller)
	{
		stream.rewind ();
		if (plugin.controller->setComponentState (&stream) != kResultTrue) throw std::runtime_error ("Controller state synchronization failed.");
		if (controllerBytes > 0)
		{
			ResizableMemoryIBStream controllerStream (controllerBytes);
			int32 controllerWritten {};
			if (controllerStream.write (const_cast<uint8_t*> (componentData + componentBytes), static_cast<int32> (controllerBytes), &controllerWritten) != kResultTrue)
				throw std::runtime_error ("Controller state buffering failed.");
			controllerStream.rewind ();
			if (plugin.controller->setState (&controllerStream) != kResultTrue) throw std::runtime_error ("Controller state restore failed.");
		}
	}
}

void processStereo (ActivePlugin& plugin, std::vector<uint8_t>& payload)
{
	if (payload.size () < sizeof (uint32_t)) throw std::runtime_error ("Process payload is truncated.");
	uint32_t frames {};
	std::memcpy (&frames, payload.data (), sizeof (frames));
	size_t expectedBytes = sizeof (uint32_t) + static_cast<size_t> (frames) * 2 * sizeof (float);
	if (frames > static_cast<uint32_t> (plugin.maximumFrames) || payload.size () != expectedBytes)
	{
		std::ostringstream diagnostic;
		diagnostic << "Process payload shape is invalid: frames=" << frames << ", maximumFrames=" << plugin.maximumFrames
			<< ", payloadBytes=" << payload.size () << ", expectedBytes=" << expectedBytes << '.';
		throw std::runtime_error (diagnostic.str ());
	}
	if (frames == 0) { payload.clear (); appendValue (payload, frames); return; }
	plugin.outputChanges.clearQueue ();
	plugin.outputEvents.clear ();
	plugin.data.numSamples = static_cast<int32> (frames);
	const auto* source = reinterpret_cast<const float*> (payload.data () + sizeof (uint32_t));
	for (int32 bus = 0; bus < plugin.data.numInputs; ++bus)
		for (int32 channel = 0; channel < plugin.data.inputs[bus].numChannels; ++channel)
		{
			auto* destination = plugin.data.inputs[bus].channelBuffers32[channel];
			for (uint32_t frame = 0; frame < frames; ++frame) destination[frame] = source[frame * 2 + std::min<int32> (channel, 1)];
		}
	for (int32 bus = 0; bus < plugin.data.numOutputs; ++bus)
		for (int32 channel = 0; channel < plugin.data.outputs[bus].numChannels; ++channel)
			std::fill_n (plugin.data.outputs[bus].channelBuffers32[channel], frames, 0.f);
	if (plugin.processor->process (plugin.data) != kResultTrue) throw std::runtime_error ("The plug-in rejected the process block.");
	plugin.inputChanges.clearQueue ();
	plugin.inputEvents.clear ();
	std::vector<uint8_t> output;
	appendValue (output, frames);
	for (uint32_t frame = 0; frame < frames; ++frame)
		for (int32 channel = 0; channel < 2; ++channel)
		{
			float sample = 0.f;
			if (plugin.mainOutputBus >= 0 && plugin.data.outputs[plugin.mainOutputBus].numChannels > 0)
				sample = plugin.data.outputs[plugin.mainOutputBus].channelBuffers32[
					std::min<int32> (channel, plugin.data.outputs[plugin.mainOutputBus].numChannels - 1)][frame];
			if (!std::isfinite (sample)) throw std::runtime_error ("The plug-in produced non-finite samples.");
			appendValue (output, sample);
		}
	payload = std::move (output);
	plugin.context.projectTimeSamples += frames;
}

int runWorker (const Arguments& args)
{
	std::ifstream requests (args.requestPath, std::ios::binary);
	std::ofstream responses (args.responsePath, std::ios::binary);
	if (!requests || !responses) throw std::runtime_error ("Worker pipe connection failed.");
	std::unique_ptr<ActivePlugin> plugin;
	for (;;)
	{
		WorkerHeader header {};
		if (!readValue (requests, header)) return 0;
		if (header.magic != kWorkerMagic || header.version != kWorkerVersion || header.payloadBytes > kMaximumWorkerPayload)
			throw std::runtime_error ("Worker request header is invalid.");
		std::vector<uint8_t> payload;
		if (!readBytes (requests, payload, header.payloadBytes)) throw std::runtime_error ("Worker request payload is truncated.");
		try
		{
			auto operation = static_cast<WorkerOperation> (header.operation);
			if (operation == WorkerOperation::Ping)
			{
				if (!plugin)
				{
					Arguments pluginArgs = args;
					plugin = createPlugin (pluginArgs);
				}
				std::vector<uint8_t> metadata;
				appendValue (metadata, static_cast<uint32_t> (countChannels (*plugin->component, kInput)));
				appendValue (metadata, static_cast<uint32_t> (countChannels (*plugin->component, kOutput)));
				appendValue (metadata, static_cast<uint32_t> (plugin->processor->getLatencySamples ()));
				appendValue (metadata, static_cast<uint32_t> (plugin->parameters.size ()));
				for (const auto& parameter : plugin->parameters)
				{
					appendValue (metadata, static_cast<uint32_t> (parameter.id));
					double normalized = plugin->controller->getParamNormalized (parameter.id);
					appendValue (metadata, normalized);
					std::string title = parameterTitle (parameter.title);
					appendValue (metadata, static_cast<uint32_t> (title.size ()));
					metadata.insert (metadata.end (), title.begin (), title.end ());
					appendValue (metadata, parameter.defaultNormalizedValue);
					appendValue (metadata, static_cast<uint32_t> ((parameter.flags & ParameterInfo::kIsReadOnly) != 0));
					std::string units = parameterTitle (parameter.units);
					appendValue (metadata, static_cast<uint32_t> (units.size ()));
					metadata.insert (metadata.end (), units.begin (), units.end ());
					String128 displayText {};
					std::string display;
					if (plugin->controller->getParamStringByValue (parameter.id, normalized, displayText) == kResultTrue)
						display = parameterTitle (displayText);
					appendValue (metadata, static_cast<uint32_t> (display.size ()));
					metadata.insert (metadata.end (), display.begin (), display.end ());
				}
				writeResponse (responses, header.requestId, true, metadata, "Native VST3 worker ready.");
			}
			else if (operation == WorkerOperation::Process)
			{
				if (!plugin) throw std::runtime_error ("The worker is not initialized.");
				processStereo (*plugin, payload);
				writeResponse (responses, header.requestId, true, payload, "");
			}
			else if (operation == WorkerOperation::SetParameter)
			{
				if (!plugin || payload.size () != sizeof (uint32_t) + sizeof (double)) throw std::runtime_error ("Parameter payload is invalid.");
				uint32_t id {}; double value {};
				std::memcpy (&id, payload.data (), sizeof (id));
				std::memcpy (&value, payload.data () + sizeof (id), sizeof (value));
				if (!std::isfinite (value) || value < 0 || value > 1 || !plugin->controller) throw std::runtime_error ("Parameter value is invalid.");
				if (plugin->controller->setParamNormalized (id, value) != kResultTrue) throw std::runtime_error ("Parameter update failed.");
				int32 queueIndex {}; IParamValueQueue* queue = plugin->inputChanges.addParameterData (id, queueIndex); int32 pointIndex {};
				if (!queue || queue->addPoint (0, value, pointIndex) != kResultTrue) throw std::runtime_error ("Parameter queue update failed.");
				writeResponse (responses, header.requestId, true, {}, "");
			}
			else if (operation == WorkerOperation::GetState)
			{
				if (!plugin) throw std::runtime_error ("The worker is not initialized.");
				writeResponse (responses, header.requestId, true, captureState (*plugin), "");
			}
			else if (operation == WorkerOperation::SetState)
			{
				if (!plugin) throw std::runtime_error ("The worker is not initialized.");
				restoreState (*plugin, payload);
				writeResponse (responses, header.requestId, true, {}, "");
			}
			else if (operation == WorkerOperation::QueueMidiEvents)
			{
				if (!plugin || payload.size () < sizeof (uint32_t)) throw std::runtime_error ("MIDI event payload is invalid.");
				uint32_t count {};
				std::memcpy (&count, payload.data (), sizeof (count));
				if (count > 4096 || payload.size () != sizeof (uint32_t) + static_cast<size_t> (count) * 20)
					throw std::runtime_error ("MIDI event payload shape is invalid.");
				if (count > 0 && plugin->eventInputBus < 0) throw std::runtime_error ("The plug-in has no active MIDI event input bus.");
				plugin->inputEvents.clear ();
				const uint8_t* cursor = payload.data () + sizeof (uint32_t);
				for (uint32_t index = 0; index < count; ++index, cursor += 20)
				{
					uint32_t kind {}; int32_t channel {}, note {}, offset {}; float velocity {};
					std::memcpy (&kind, cursor, 4); std::memcpy (&channel, cursor + 4, 4); std::memcpy (&note, cursor + 8, 4);
					std::memcpy (&velocity, cursor + 12, 4); std::memcpy (&offset, cursor + 16, 4);
					if (kind > 1 || channel < 0 || channel > 15 || note < 0 || note > 127 || !std::isfinite (velocity) || velocity < 0 || velocity > 1 || offset < 0 || offset >= plugin->maximumFrames)
						throw std::runtime_error ("MIDI event value is outside the active process block.");
					Event event {};
					event.busIndex = plugin->eventInputBus; event.sampleOffset = offset; event.ppqPosition = 0.; event.flags = Event::kIsLive;
					if (kind == 0) { event.type = Event::kNoteOnEvent; event.noteOn.channel = static_cast<int16> (channel); event.noteOn.pitch = static_cast<int16> (note); event.noteOn.velocity = velocity; event.noteOn.tuning = 0; event.noteOn.length = 0; event.noteOn.noteId = -1; }
					else { event.type = Event::kNoteOffEvent; event.noteOff.channel = static_cast<int16> (channel); event.noteOff.pitch = static_cast<int16> (note); event.noteOff.velocity = velocity; event.noteOff.tuning = 0; event.noteOff.noteId = -1; }
					if (plugin->inputEvents.addEvent (event) != kResultTrue) throw std::runtime_error ("MIDI event queue is full.");
				}
				writeResponse (responses, header.requestId, true, {}, "");
			}
			else if (operation == WorkerOperation::Shutdown)
			{
				writeResponse (responses, header.requestId, true, {}, "");
				return 0;
			}
			else if (operation == WorkerOperation::Crash) std::abort ();
			else if (operation == WorkerOperation::Hang) for (;;) std::this_thread::sleep_for (std::chrono::seconds (1));
			else throw std::runtime_error ("Unsupported worker operation.");
		}
		catch (const std::exception& exception)
		{
			writeResponse (responses, header.requestId, false, {}, exception.what ());
		}
	}
}
}

int wmain (int argc, wchar_t** argv)
{
	Arguments args;
	std::string error;
	if (!parseArguments (argc, argv, args, error)) { printFailure (error); return 2; }
	try
	{
#if defined(EDMG_VST3_SCANNER_EXECUTABLE)
		if (args.operation == "--scan-module") return scanModule (args);
		printFailure ("The scanner supports only --scan-module.");
#else
		if (args.operation == "--qualify") return qualify (args);
		if (args.operation == "--worker") return runWorker (args);
		printFailure ("The host supports only --qualify and --worker.");
#endif
		return 2;
	}
	catch (const std::exception& exception)
	{
		printFailure (exception.what ());
		return 1;
	}
	catch (...)
	{
#if defined(EDMG_VST3_SCANNER_EXECUTABLE)
		printFailure ("Unknown native VST3 scanner failure.");
#else
		printFailure ("Unknown native VST3 host failure.");
#endif
		return 1;
	}
}
