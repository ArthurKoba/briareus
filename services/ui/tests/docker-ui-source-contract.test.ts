import {describe,expect,it} from "bun:test"
import {readFileSync,existsSync} from "node:fs"
import {resolve} from "node:path"

const root=resolve(import.meta.dir,"..")
const file=(relative:string)=>readFileSync(resolve(root,relative),"utf8")

describe("self-contained Control Panel Docker source inputs",()=>{
  it("copies Vite's local relative config dependency into the build stage",()=>{
    const config=file("vite.config.ts")
    const image=file("Dockerfile")
    const filter=file("Dockerfile.dockerignore").split(/\r?\n/)
    if(config.includes('from "./local-http-proxy"')){
      expect(existsSync(resolve(root,"local-http-proxy.ts"))).toBe(true)
      expect(image).toContain("COPY services/ui/local-http-proxy.ts ./")
      expect(filter).toContain("!services/ui/local-http-proxy.ts")
    }
    expect(image).toContain("COPY services/ui/src ./src")
    expect(filter).toContain("!services/ui/src/**")
    expect(file("docker-compose.yaml")).toContain("dockerfile: services/ui/Dockerfile")
    expect(file("docker-compose.yaml")).toContain("context: ../..")
  })
})
