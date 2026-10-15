/** Bounded presentation of already-decoded text. No file I/O or authority. */
export const PREVIEW_TEXT_LIMIT=262_144
export const PREVIEW_PAGE_SIZE=8192
export interface TextPage {start:number;end:number;firstLine:number;lastLine:number}
export interface TextPreview {text:string;pages:TextPage[];truncated:boolean}
function boundary(text:string,end:number):number {
  const before=text.charCodeAt(end-1),after=text.charCodeAt(end)
  if((before>=0xd800&&before<=0xdbff&&after>=0xdc00&&after<=0xdfff)||
    (before===13&&after===10))return end-1
  return end
}
export function buildTextPreview(input:string):TextPreview {
  const text=input.slice(0,boundary(input,Math.min(input.length,PREVIEW_TEXT_LIMIT)))
  const pages:TextPage[]=[]
  let start=0,line=1
  do{
    let end=boundary(text,Math.min(text.length,start+PREVIEW_PAGE_SIZE))
    if(end<text.length){
      const newline=text.lastIndexOf('\n',end-1)
      if(newline>=start+PREVIEW_PAGE_SIZE/2)end=newline+1
    }
    const fragment=text.slice(start,end)
    const newlines=fragment.split('\n').length-1
    pages.push({start,end,firstLine:line,lastLine:line+newlines-(fragment.endsWith('\n')?1:0)})
    line+=newlines;start=end
  }while(start<text.length)
  return {text,pages,truncated:text.length<input.length}
}
export function findTextMatches(text:string,query:string):{positions:number[];limited:boolean} {
  const positions:number[]=[]
  if(!query||query.length>128)return {positions,limited:false}
  let offset=0
  while(offset<=text.length){
    const at=text.indexOf(query,offset)
    if(at<0)return {positions,limited:false}
    if(positions.length===500)return {positions,limited:true}
    positions.push(at);offset=at+Math.max(1,query.length)
  }
  return {positions,limited:false}
}
export function pageForMatch(pages:readonly TextPage[],offset:number):number {
  const index=pages.findIndex(page=>offset>=page.start&&offset<page.end)
  return index<0?0:index
}
