package com.x.svc

class Service(private val repo: Repo) {
    fun handle(name: String): Boolean = repo.save(name)
}
