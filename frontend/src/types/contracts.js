/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,calibration_version:number}} AnalysisJob */
/** @typedef {{id:number,dataset_id:number,version:number,default_offset_m:number,run_offsets:Object,note:string,active:boolean}} Calibration */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,calibration_version:number,suspended_reason:string,current_calibration_version:number}} ReportSchedule */
export {};
