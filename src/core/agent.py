from src.core.models import LLMResponse, TaskResult, CallChainEntry, BuilderInput, Subtask, ExecutionPlan
from src.core.task_router import TaskRouter
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.builder import Builder
import time
import uuid


class Agent:
    """
    负责任务状态机
    """

    def __init__(self, task_router: TaskRouter, router: Router, llmclient: LLMClient, builder: Builder):
        self.task_router = task_router
        self.router = router
        self.llm_client = llmclient
        self.builder = builder

    def run(self, user_input: str) ->dict:
        """
        READY → PLANNING → ROUTING → CALLING → SUCCESS/PARTIAL_SUCCESS/FAILED
        """
        task_id = "task_" + uuid.uuid4().hex
        results:list[TaskResult] = []
        call_chain:list[CallChainEntry] = []
        
        # PLANNING
        plan = self.task_router.route_task(user_input)
        if not plan or not plan.subtasks:
            return self._build_response(
                task_id,
                "FAILED",
                results,
                call_chain
            )

        for subtask in plan.subtasks:
            capability_required = subtask.capability
            prompt = subtask.prompt
            failed_models = []
            success = False

            while not success:
                model_info = self.router.get_model(capability_required,failed_models)
            
            # ROUTING 

                if "error" in model_info:
                    break
                
                output_type = "text" if capability_required == "text-generation" else "image"
            # CALLING
                response = self.llm_client.call(
                    model_name = model_info["model_name"], 
                    endpoint = model_info["endpoint"], 
                    api_key = model_info["api_key"], 
                    prompt = prompt, 
                    output_type = output_type
                    )


                attempted_at = str(time.time())
                if response.status == "SUCCESS":                   
                    call_chain.append (CallChainEntry(
                        model_name = model_info["model_name"],
                        capability = capability_required,
                        status = "SUCCESS",
                        attempted_at = attempted_at
                    ))
                    results.append (response.data)
                    success = True


                else:
                    call_chain.append(CallChainEntry(
                        model_name = model_info["model_name"],
                        capability = capability_required,
                        status = "FAILED",
                        error_code = response.error_code,
                        attempted_at = attempted_at
                    ))          
                    failed_models.append(model_info["model_name"])

            if not success :
                if results:
                    return self._build_response(task_id,"PARTIAL_SUCCESS",results,call_chain)
                else:
                    return self._build_response(task_id,"FAILED",results,call_chain)
                
        
        return self._build_response(task_id,"SUCCESS",results,call_chain)
    

    def _build_response(self,task_id: str,final_status: str,results: list,call_chain: list) ->dict:
        """拼装response"""
        builder_input = BuilderInput(
            task_id = task_id,
            final_status = final_status,
            results = results,
            call_chain = call_chain
        )
        return self.builder.build(builder_input)
    
            





                