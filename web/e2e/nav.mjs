// Shared navigation helpers for the browser tests. The app has a sidebar; on small screens it is a drawer behind the "Open menu" button.
const SECTIONS = { Overview: "", Chat: "/chat", Story: "/storyboard", Storyboard: "/storyboard", Assets: "/assets", Shots: "/shots", Costs: "/costs", Discarded: "/discarded" };
export async function go(page, name) {
  const section = SECTIONS[name];
  if (section === undefined) throw new Error(`go(): unknown page ${name}`);
  // the sidebar only exists once the project has loaded; wait for it (attached, not necessarily visible: on a phone it is in a drawer)
  const nav = page.locator('nav[aria-label="Project"]').first();
  await nav.waitFor({ state: "attached", timeout: 15000 });
  const link = section === "" ? nav.locator("a").first() : nav.locator(`a[href$="${section}"]`).first();
  if (!(await link.isVisible())) await page.getByRole("button", { name: "Open menu" }).click();
  await link.click();
}
