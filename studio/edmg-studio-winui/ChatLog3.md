## :bust_in_silhouette:  (9/11/2026 7:12 AM)
"Your Director draft is already applied, but Reactive Lab has no analyzed audio data yet.
1.	Click Overview + Director near the top.
2.	Under Source audio, click Choose audio and select your song.
3.	Click Upload and analyze and wait for analysis to finish.
4.	Return to Reactive Lab. The generated beats/keyframes should appear.
5.	Review them, click Apply Workspace draft, then proceed to Render.
If audio was already analyzed, click Discard local edits and reload, then Refresh workspace. The yellow warning is validation—not a crash."


would that not undo the whole flow from the director generate draft and such?
## :speech_balloon: Microsoft Foundry
I’ll verify how Director drafts, Reactive Lab edits, and workspace refresh are persisted so the answer matches the current Studio behavior.

1. Search: Discard local edits|Refresh workspace|Apply Workspace draft|Upload and analyze :white_check_mark:
1. Search: discard.*local|reload.*workspace|refreshWorkspace|director.*draft|workspace d... :white_check_mark:
1. Search: ReloadWorkspaceDraftButton_Click|ApplyButton_Click|SaveWorkspaceDraftButton_C... :white_check_mark:
1. Search: DiscardWorkflowEditsButton_Click|RefreshWorkspaceButton_Click|UploadAnalyzeBu... :white_check_mark:
1. Search: class WorkspaceDraft|WorkspaceDraft|Save.*Draft|Get.*Draft|Apply.*Draft :white_check_mark:

1. Read: WorkspacePage.xaml.cs :white_check_mark:
1. Read: WorkspacePage.xaml.cs :white_check_mark:
1. Read: ReactiveLabPage.xaml.cs :white_check_mark:
1. Read: ReactiveLabPage.xaml.cs :white_check_mark:
The key distinction is saved shared draft versus unsaved screen edits; I’m checking whether re-analysis replaces the saved draft itself.

1. Search: def analyze|analyze_audio|AnalyzeAudio|workflow.*prepare|prepare.*workflow :white_check_mark:
1. Search: analysis.*workflow|workflow.*analysis|director_workflow|workflow_draft :white_check_mark:
1. Search: @router.*analy|async def .*analy|def .*analy :white_check_mark:
1. Search: prepare_workflow|workflow.*draft|draft.*workflow :white_check_mark:
1. Search: def analyze_audio\(|analyze_audio= :white_check_mark:
1. Search: last_plan|prepare_workflow :white_check_mark:
1. Read: app.py :white_check_mark:
**No—not the already applied Director flow or active Timeline.** The wording is easy to misread:

- **Upload and analyze** saves the audio analysis and prepares a **new shared Workspace draft** containing Director scenes plus reactive keyframes. The currently applied plan and Timeline remain active until you explicitly apply this combined draft.
- **Discard local edits and reload** discards only **unsaved Reactive Lab edits on that screen**, then reloads the saved shared Workspace draft. It does not delete the saved Director draft.
- **Refresh workspace** reloads persisted project data; it does not reset the project.

The only caveat: re-analyzing audio regenerates the **pending shared draft**, so previously saved-but-not-applied draft refinements may be replaced. If you have unsaved Director edits, save them first—the UI should block analysis and warn you rather than silently discard them.

___

## :bust_in_silhouette:
so what do i do?
## :speech_balloon: Microsoft Foundry
Do this:

1. In **Overview + Director**, check whether your Director changes are saved. If **Save draft edits** is enabled, click it first.
2. Under **Source audio**, choose the same song used for the project and click **Upload and analyze**.
3. Wait for **Audio analysis ready**.
4. Open **Reactive Lab**. If it still shows stale or missing data, click **Discard local edits and reload** there.
5. Review the generated keyframes, make any adjustments, then click **Apply Workspace draft**.
6. Continue to **Render**.

Do **not** click **Prepare draft** or regenerate the Director direction again. The analysis step supplies the missing audio data and creates the combined review draft; your currently applied Timeline remains intact until step 5.

___

## :bust_in_silhouette:
that makes no sense, why would the audio have to be analyzed twice? shouldnt the keyframes be applied with the draft?
