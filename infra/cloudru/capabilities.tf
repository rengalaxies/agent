# Scoped catalog lookup for next deployment plan. Read only.
data "cloudru_evolution_compute_flavor_collection" "available" {
  project_id = var.project_id
  page_size = 1000
}
data "cloudru_evolution_compute_image_collection" "available" {
  project_id = var.project_id
  page_size = 100
}
output "deployment_candidates" {
  description = "Limited VM flavors and Ubuntu images in approved project"
  value = {
    project_id = var.project_id
    flavors = [for f in coalesce(data.cloudru_evolution_compute_flavor_collection.available.flavors, []) : {
      id = f.id
      name = f.name
      cpu = f.cpu
      ram = f.ram
    } if (f.cpu == 2 && f.ram == 4) || (f.cpu == 8 && f.ram == 32) || (f.cpu == 4 && f.ram == 32)]
    images = [for i in coalesce(data.cloudru_evolution_compute_image_collection.available.images, []) : {
      id = i.id
      name = i.name
      min_disk = i.min_disk
    } if strcontains(lower(i.name), "ubuntu")]
  }
}
