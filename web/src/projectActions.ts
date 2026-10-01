import { api, getToken } from "./api";
import { promptDialog } from "./dialogs";

/** Download the whole project folder as a zip (the browser streams it; nothing is held in memory). */
export function downloadProjectZip(name: string, includeDiscarded = false) {
  const a = document.createElement("a");
  a.href = `/api/projects/${encodeURIComponent(name)}/export-project?token=${encodeURIComponent(getToken())}${includeDiscarded ? "&include_discarded=1" : ""}`;
  a.download = `${name}.zip`; document.body.appendChild(a); a.click(); a.remove();
}

/** Ask the user to type the project name, then MOVE the project to the trash (it can be restored). Returns true when it was moved. */
export async function deleteProject(name: string): Promise<boolean> {
  const typed = await promptDialog(
    `Type the project name (${name}) to move it to the trash.\n\nNothing is erased: the whole folder is moved to the trash and can be restored from the Projects page.`,
    { title: "Delete project", ok: "Move to trash" });
  if (typed === null) return false;
  if (typed.trim() !== name) throw new Error("The name you typed does not match, so nothing was deleted.");
  await api("DELETE", `/api/projects/${encodeURIComponent(name)}`, { confirm: typed.trim() });
  return true;
}
