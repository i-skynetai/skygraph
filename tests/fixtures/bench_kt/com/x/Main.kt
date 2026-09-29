package com.x

import com.x.svc.Repo
import com.x.svc.Service

fun main() {
    val s = Service(Repo())
    s.handle("x")
}
