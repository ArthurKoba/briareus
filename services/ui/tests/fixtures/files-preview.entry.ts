/** Read-only component fixture, never imported by the application entry.
 * Bundled separately for browser acceptance without an extra dev-server
 * process. The harness supplies local byte data; no product API is called.
 */
import {createApp,h,reactive} from "vue"
import {createI18n} from "vue-i18n"
import FilePreview from "../../src/features/files-preview/ui/FilePreviewPane.vue"
import "../../src/app/styles.css"
const state=reactive<{path:string;status:"empty"|"ready"|"denied"|"unavailable";readResult:unknown;content?:string;designPreview?:boolean}>({path:"",status:"empty",readResult:undefined,content:"",designPreview:false})
const i18n=createI18n({legacy:false,locale:"ru",messages:{ru:{},en:{}}})
createApp({setup:()=>()=>h(FilePreview,{...state})}).use(i18n).mount("#fixture")
Object.assign(window,{__fileFixture:{state,i18n}})
