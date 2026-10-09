/** Accepted A5 source-only ProviderCatalog never establishes connectivity. */
import { DraftContractError,draftRecordFields,draftList,draftString,draftBoolean,draftSourceDefault } from "@/features/platform/api/draft/source-contract"
export interface SourceCatalogEntry {provider:string;auth_types:string[];connectivity_status:string}
export interface SourceProviderCatalog {providers:SourceCatalogEntry[];network_verification_available:boolean}
export function parseSourceProviderCatalog(raw:unknown):SourceProviderCatalog {
  const v=draftRecordFields(raw,["providers","network_verification_available"])
  const providers=draftList(v.providers,item=>{
    const p=draftRecordFields(item,["provider","auth_types","connectivity_status"])
    const provider=draftString(p.provider)
    if(!["github","gitlab","coolify","signoz","grafana","zoomies"].includes(provider))throw new DraftContractError("provider_unknown")
    const auth_types=draftList(p.auth_types,draftString)
    if(!auth_types.length||new Set(auth_types).size!==auth_types.length)throw new DraftContractError("provider_auth_invalid")
    const connectivity_status=draftSourceDefault(p.connectivity_status,"unverified",draftString)
    if(connectivity_status!=="unverified")throw new DraftContractError("provider_connectivity_future_schema")
    return {provider,auth_types,connectivity_status}
  })
  if(new Set(providers.map(p=>p.provider)).size!==providers.length)throw new DraftContractError("provider_catalog_duplicate")
  const network_verification_available=draftSourceDefault(v.network_verification_available,false,draftBoolean)
  if(network_verification_available)throw new DraftContractError("provider_verification_not_accepted")
  // A5 is always unverified; never infer connectivity from a declared auth type.
  return {providers,network_verification_available}
}
